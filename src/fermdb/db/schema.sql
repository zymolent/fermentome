-- fermdb core relational schema, version 2.
--
-- Applied by src/fermdb/db/__init__.py. Nothing else in the codebase opens the database, so the
-- storage engine can be changed by editing that one module (PLAN.md X.2).
--
-- Reading conventions used throughout, from docs/reference/CONVENTIONS.md:
--
--   zone        Every table holding a fact carries `zone` CHECK (zone IN ('R','H','I')):
--               R = reported exactly as the source stated it, H = harmonized (rebuildable from R
--               by recorded code), I = inferred (statistical / model / LLM; may not support a
--               conclusion until a curator promotes it). Pure junction rows inherit the zone of
--               their parent and do not repeat the column, and every such table says so on its
--               own definition -- an unexplained missing `zone` is a bug, not a style.
--   NULL/NA     NULL = never recorded. 'NA' = recorded as not applicable. 'unknown' = recorded
--               but unresolved. Three different states; never coerced into each other or zero.
--   evidence    Free text naming the source. `confidence` is one of four values:
--                 'unverified'  asserted, but never checked against a source. A real and common
--                               state and NOT the same as 'low': 'low' means checked and weak.
--                 'low' | 'medium' | 'high'
--               Never 'high' for a value recalled rather than checked (that is 'medium' at best,
--               or 'unverified' if it was never checked at all).
--   numerics    A numeric column that can be "recorded but unresolved" carries a companion
--               `<col>_state TEXT CHECK (<col>_state IN ('recorded','not_applicable','unknown'))`.
--               The numeric is NULL unless the state is 'recorded'; numeric NULL *and* state NULL
--               means the facet was never recorded at all. A bare REAL column cannot hold the
--               three states CONVENTIONS.md requires, because 'NA' and 'unknown' are not numbers.
--   as_reported A first-class facet column that is parsed out of prose carries a
--               `<facet>_as_reported TEXT` shadow holding the source's verbatim string. The
--               parsed column is Zone H and may be rebuilt; the shadow is Zone R and is never
--               overwritten or re-parsed in place. Facets with no first-class column use
--               `condition_context_facet`, which has an `as_reported` column of its own.
--   coordinates 0-based half-open [start, end). Length is end - start. Strand is +1/-1/0.
--   fractions   Rates and fractions are stored in [0, 1] with a CHECK, never as percentages.
--
-- Polymorphic references (assertion.subject_id, curation_event.target_id, bottleneck.node) are
-- plain TEXT and deliberately carry no foreign key: SQLite cannot express "FK into one of six
-- tables". Their integrity is checked by the traceability walk of PLAN.md J.5, which runs in CI.
-- Everything that can be a real foreign key is one.

PRAGMA foreign_keys = ON;


-- ---------------------------------------------------------------------------------------------
-- 0. Database metadata
-- ---------------------------------------------------------------------------------------------

-- Not a fact table, so no zone. open_db() reads 'schema_version' and refuses a database written
-- by a newer schema rather than migrating it implicitly.
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);


-- ---------------------------------------------------------------------------------------------
-- 1. Controlled vocabularies
--
-- These are closed, versioned vocabularies rather than facts, so they carry no zone. They are
-- seeded here because a foreign key into an empty table makes every insert fail; they should move
-- to repo-tier TSV loaded by the curation CLI once that exists (CONVENTIONS.md "Curation").
-- They exist as *tables* rather than as CHECK lists specifically so that product-specific values
-- live in data and not in code (CONVENTIONS.md: no `if product == 'ethanol'`).
-- ---------------------------------------------------------------------------------------------

CREATE TABLE predicate (
    id              TEXT PRIMARY KEY,
    vocab_version   INTEGER NOT NULL,
    biolink_mapping TEXT,           -- NULL = no Biolink equivalent recorded yet
    ro_mapping      TEXT,
    definition      TEXT,
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'deprecated'))
);

-- PLAN.md J.2. Closed because an open predicate vocabulary makes the graph unqueryable within a
-- year; versioned because it will need to grow.
INSERT INTO predicate (id, vocab_version) VALUES
    ('affects_production_of', 1),
    ('affects_tolerance_to', 1),
    ('affects_yield_of', 1),
    ('catalyzes', 1),
    ('transports', 1),
    ('regulates', 1),
    ('is_expressed_under', 1),
    ('is_differentially_expressed_in', 1),
    ('co_expressed_with', 1),
    ('is_bottleneck_for', 1),
    ('competes_with', 1),
    ('is_required_for', 1),
    ('confers_resistance_to', 1),
    ('is_localized_to', 1),
    ('has_variant_associated_with', 1),
    ('improves_when_modified_by', 1),
    ('interacts_with', 1);

CREATE TABLE step_role (
    id         TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    definition TEXT
);

-- docs/design/ISOBUTANOL_PROGRAM.md section 3.
INSERT INTO step_role (id, label) VALUES
    ('AHAS', 'Acetolactate synthase'),
    ('KARI', 'Ketol-acid reductoisomerase'),
    ('DHAD', 'Dihydroxyacid dehydratase'),
    ('KDC', '2-ketoacid decarboxylase'),
    ('ADH', 'Alcohol dehydrogenase'),
    ('transporter', 'Membrane carrier'),
    ('cofactor_cycle', 'Cofactor balancing step');

CREATE TABLE compartment_strategy (
    id         TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    definition TEXT,
    source     TEXT NOT NULL
);

-- ISOBUTANOL_PROGRAM.md section 2 (A-D) plus MITOCHONDRIAL_PROGRAM.md section 4 (E).
INSERT INTO compartment_strategy (id, label, source) VALUES
    ('A_native_split', 'Native split: Ilv in matrix, Ehrlich in cytosol',
     'docs/design/ISOBUTANOL_PROGRAM.md section 2'),
    ('B_cytosolic_relocalization', 'Ilv enzymes relocalized to the cytosol',
     'docs/design/ISOBUTANOL_PROGRAM.md section 2'),
    ('C_mitochondrial_ehrlich', 'Ehrlich pathway targeted to the matrix',
     'docs/design/ISOBUTANOL_PROGRAM.md section 2'),
    ('D_alternative_compartment', 'Peroxisomal or other-organelle assembly',
     'docs/design/ISOBUTANOL_PROGRAM.md section 2'),
    ('E_mtdna_encoded', 'Recoded Ehrlich enzymes encoded in mtDNA',
     'docs/design/MITOCHONDRIAL_PROGRAM.md section 4');

-- v11. The sixth row, and the only one that is not a compartment.
--
-- A-E are answers to "which compartment does each step run in", and every one of them presupposes
-- a eukaryotic host with organelles to choose between. A prokaryote has no such choice: there is
-- one cytoplasm and the whole route runs in it. Before this row the only storable answers for
-- such a build were NULL ("not recorded") and the extractor's 'NA' -- both of which say the
-- record is incomplete, when in fact it is complete and the question does not apply. PLAN.md
-- phase 1 curates "every published microbial isobutanol production strain, in any host", so those
-- builds are in scope by the plan and were unrepresentable by the vocabulary.
--
-- WHY THIS NAME. Not 'F_no_compartmentalization': that reads as a sixth compartmentalization
-- choice -- the decision to leave the pathway uncompartmented -- and it is not a decision at all.
-- Not 'F_prokaryotic_cytoplasm' or 'F_bacterial': naming a taxon or a compartment would make the
-- row mean "the bacterial one" rather than "the one where the question does not arise", and the
-- id has to still read correctly for the C. glutamicum and B. subtilis configurations that phase
-- 1 will bring. 'single_compartment_host' names the property of the HOST that removes the choice,
-- which is the thing all of those builds actually have in common. A host that does have internal
-- compartments and a build that declines to use them is NOT this row: that is a real decision and
-- would need its own.
INSERT INTO compartment_strategy (id, label, definition, source) VALUES
    ('F_single_compartment_host', 'Single-compartment host: no compartment choice to make',
     'The host has no internal compartment a pathway step could be placed in, so the whole route '
     || 'runs in its single cytoplasm and strategies A-E do not apply. This is the absence of a '
     || 'compartmentalization decision, not a sixth compartment. Distinct from NULL (not '
     || 'recorded) and from the extractor''s ''NA''/''unknown'' (the paper does not say): here '
     || 'the record is complete and the question does not arise.',
     'PLAN.md phase 1 scope, ''any host''; first required by doi:10.1016/j.jbiotec.2022.09.012, '
     || 'which states ''The isobutanol producing strain E. coli HM501 was used in this work as a '
     || 'host strain''.');


-- ---------------------------------------------------------------------------------------------
-- 2. Biological entities
-- ---------------------------------------------------------------------------------------------

CREATE TABLE organism (
    id          TEXT PRIMARY KEY,           -- YAA:ORG:...
    ncbi_taxid  INTEGER,                    -- NULL = never recorded, not "unknown taxon"
    name        TEXT NOT NULL,
    rank        TEXT,
    zone        TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence    TEXT NOT NULL,
    confidence  TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);

-- lifestyle_tags[] as rows, not a comma-separated column: a delimited list in a column cannot be
-- queried or constrained, and 'crabtree_positive' is a claim that needs its own evidence.
CREATE TABLE organism_lifestyle_tag (
    organism_id TEXT NOT NULL REFERENCES organism(id) ON DELETE CASCADE,
    tag         TEXT NOT NULL,
    zone        TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence    TEXT NOT NULL,
    confidence  TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high')),
    PRIMARY KEY (organism_id, tag)
);

CREATE TABLE strain (
    id             TEXT PRIMARY KEY,        -- YAA:STRAIN:cen-pk113-7d
    organism_id    TEXT NOT NULL REFERENCES organism(id),
    canonical_name TEXT NOT NULL,
    -- `class` is curated, evidenced and frequently arguable (PLAN.md C.2), hence its own
    -- evidence/confidence on the row rather than a bare enum.
    class          TEXT CHECK (class IN ('laboratory', 'industrial', 'wild', 'engineered',
                                         'evolved', 'unknown')),
    zone           TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence       TEXT NOT NULL,
    confidence     TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);

-- "Ethanol Red" and "industrial yeast" resolve here. Every identifier that is not the canonical
-- one is an alias carrying its own source and confidence (CONVENTIONS.md "Identifiers").
CREATE TABLE strain_alias (
    id         TEXT PRIMARY KEY,
    strain_id  TEXT NOT NULL REFERENCES strain(id) ON DELETE CASCADE,
    alias      TEXT NOT NULL,
    source     TEXT NOT NULL,
    zone       TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence   TEXT NOT NULL,
    confidence TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high')),
    UNIQUE (strain_id, alias)
);

-- A DAG, not a tree: crosses and hybrids have two parents, so parentage is an edge table.
CREATE TABLE strain_lineage (
    parent_strain_id TEXT NOT NULL REFERENCES strain(id),
    child_strain_id  TEXT NOT NULL REFERENCES strain(id),
    step_type        TEXT NOT NULL,          -- cross | mutagenesis | transformation | evolution
    publication_id   TEXT REFERENCES publication(id),
    zone             TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence         TEXT NOT NULL,
    confidence       TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high')),
    PRIMARY KEY (parent_strain_id, child_strain_id, step_type),
    -- Cheapest possible cycle guard. Longer cycles are caught by the graph build, not by SQLite.
    CHECK (parent_strain_id <> child_strain_id)
);

CREATE TABLE genotype (
    id          TEXT PRIMARY KEY,
    strain_id   TEXT NOT NULL REFERENCES strain(id) ON DELETE CASCADE,
    -- Zone R: the raw genotype string is preserved verbatim, never cleaned in place.
    as_reported TEXT NOT NULL,
    -- Zone H: the parse, as JSON. Rebuildable from as_reported by recorded code.
    parsed_json TEXT,
    zone        TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence    TEXT NOT NULL,
    confidence  TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);


-- ---------------------------------------------------------------------------------------------
-- 3. Compartments and encoding genomes
--
-- A compartment is an entity with properties that constrain design, not a label (PLAN.md G.5).
--
-- THE GENETIC CODE FOLLOWS THE ENCODING GENOME, NOT THE COMPARTMENT. Translation happens where
-- the ribosome is, not where the protein ends up. Ilv2/Ilv5/Ilv3 are nuclear-encoded, translated
-- on cytosolic ribosomes under NCBI table 1, and then imported into the matrix: a
-- presequence-targeted construct needs NO recoding. Only genes physically carried on mtDNA are
-- translated in the matrix under table 3. `compartment` therefore has no `genetic_code_table`
-- column at all -- the code table hangs off `encoding_genome`, which is the thing that actually
-- determines it. An earlier version of this schema keyed the table on the compartment and would
-- have told a bench scientist to recode a construct that must not be recoded.
--
-- The matrix and the inner membrane hold proteins from BOTH genomes, so "what code does the
-- mitochondrial matrix use?" is a malformed question and the schema refuses to answer it: the
-- pair (compartment, encoding_genome) is what a sequence, a route step or a relocalization must
-- name. `compartment_encoding_genome` is a child table rather than a column on `compartment`
-- because the relation is many-to-many -- a delimited list in a column cannot be queried,
-- constrained, or pointed at by a foreign key, and its rows are exactly what the composite
-- foreign keys elsewhere in this file (`part`, `part_expression_record`, `pathway_route_step`,
-- `modification_localization_change`) use to make an impossible pairing unstorable. It follows
-- the same reasoning as `organism_lifestyle_tag` above, and each row is a claim with its own
-- evidence for the same reason.
--
-- AUTHORITY for the VALUES: NCBI Genetic Codes (tables 1 and 3) and S. cerevisiae mtDNA
-- gene content. src/fermdb/genetic_code.py -- ENCODING_GENOME_TABLE for the code tables and
-- COMPARTMENT_ENCODING_GENOMES for the pairs. The seed rows below must agree with both;
-- tests/test_schema.py fails if they drift. The two are kept as independent sources on purpose,
-- so the test is a real check rather than a tautology.
-- ---------------------------------------------------------------------------------------------

-- The genome that carries the gene, and hence the NCBI table its mRNA is read by. This is the
-- ONLY place in the schema where a genetic code table is recorded.
CREATE TABLE encoding_genome (
    id                 TEXT PRIMARY KEY,     -- 'nuclear' | 'mitochondrial'
    genetic_code_table INTEGER NOT NULL CHECK (genetic_code_table IN (1, 3)),
    table_name         TEXT NOT NULL,
    ribosome           TEXT NOT NULL,        -- where translation physically happens
    zone               TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence           TEXT NOT NULL,
    confidence         TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);

INSERT INTO encoding_genome
    (id, genetic_code_table, table_name, ribosome, zone, evidence, confidence) VALUES
    ('nuclear', 1, 'Standard', 'cytosolic', 'R',
     'NCBI Genetic Codes, table 1 (Standard)', 'unverified'),
    ('mitochondrial', 3, 'Yeast Mitochondrial', 'mitoribosome (matrix)', 'R',
     'NCBI Genetic Codes, table 3 (Yeast Mitochondrial)', 'unverified');

CREATE TABLE compartment (
    id                 TEXT PRIMARY KEY,
    import_machinery   TEXT,                -- TOM/TIM for the matrix; PTS1/PTS2 for peroxisome
    ph_estimate        REAL,                -- NULL = never recorded; do not default it to 7
    redox_estimate     REAL,
    zone               TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence           TEXT NOT NULL,
    confidence         TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);

INSERT INTO compartment (id, import_machinery, zone, evidence, confidence) VALUES
    ('cytosol', NULL, 'R',
     'NCBI Genetic Codes, table 3; S. cerevisiae mtDNA gene content', 'unverified'),
    ('nucleus', NULL, 'R',
     'NCBI Genetic Codes, table 3; S. cerevisiae mtDNA gene content', 'unverified'),
    ('endoplasmic_reticulum', 'Sec61', 'R',
     'NCBI Genetic Codes, table 3; S. cerevisiae mtDNA gene content', 'unverified'),
    ('peroxisome', 'PTS1/PTS2', 'R',
     'NCBI Genetic Codes, table 3; S. cerevisiae mtDNA gene content', 'unverified'),
    ('vacuole', NULL, 'R',
     'NCBI Genetic Codes, table 3; S. cerevisiae mtDNA gene content', 'unverified'),
    ('extracellular', NULL, 'R',
     'NCBI Genetic Codes, table 3; S. cerevisiae mtDNA gene content', 'unverified'),
    ('mitochondrial_ims', 'TOM/MIA40', 'R',
     'NCBI Genetic Codes, table 3; S. cerevisiae mtDNA gene content', 'unverified'),
    ('mitochondrial_matrix', 'TOM/TIM23', 'R',
     'NCBI Genetic Codes, table 3; S. cerevisiae mtDNA gene content', 'unverified'),
    ('mitochondrial_inner_membrane', 'TOM/TIM23/TIM22 and OXA1 (matrix-side export)', 'R',
     'NCBI Genetic Codes, table 3; S. cerevisiae mtDNA gene content', 'unverified');

-- Which genomes can encode a protein found in each compartment. Two rows for a compartment means
-- the compartment alone does not determine the code, and anything naming that compartment must
-- also name the genome. The PRIMARY KEY is what the composite foreign keys elsewhere reference.
CREATE TABLE compartment_encoding_genome (
    compartment_id  TEXT NOT NULL REFERENCES compartment(id) ON DELETE CASCADE,
    encoding_genome TEXT NOT NULL REFERENCES encoding_genome(id),
    zone            TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence        TEXT NOT NULL,
    confidence      TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high')),
    PRIMARY KEY (compartment_id, encoding_genome)
);

INSERT INTO compartment_encoding_genome
    (compartment_id, encoding_genome, zone, evidence, confidence) VALUES
    ('cytosol', 'nuclear', 'R',
     'NCBI Genetic Codes, table 3; S. cerevisiae mtDNA gene content', 'unverified'),
    ('nucleus', 'nuclear', 'R',
     'NCBI Genetic Codes, table 3; S. cerevisiae mtDNA gene content', 'unverified'),
    ('endoplasmic_reticulum', 'nuclear', 'R',
     'NCBI Genetic Codes, table 3; S. cerevisiae mtDNA gene content', 'unverified'),
    ('peroxisome', 'nuclear', 'R',
     'NCBI Genetic Codes, table 3; S. cerevisiae mtDNA gene content', 'unverified'),
    ('vacuole', 'nuclear', 'R',
     'NCBI Genetic Codes, table 3; S. cerevisiae mtDNA gene content', 'unverified'),
    ('extracellular', 'nuclear', 'R',
     'NCBI Genetic Codes, table 3; S. cerevisiae mtDNA gene content', 'unverified'),
    -- Nuclear-only: mtDNA encodes matrix and inner-membrane products, not soluble IMS residents.
    -- An earlier version of this schema filed the IMS under table 3, which was simply wrong.
    ('mitochondrial_ims', 'nuclear', 'R',
     'NCBI Genetic Codes, table 3; S. cerevisiae mtDNA gene content',
     'unverified'),
    -- Both genomes. Ilv2/Ilv5/Ilv3 arrive here nuclear-encoded and need no recoding; the handful
    -- of genes carried on mtDNA are translated here under table 3 and do.
    ('mitochondrial_matrix', 'nuclear', 'R',
     'NCBI Genetic Codes, table 3; S. cerevisiae mtDNA gene content', 'unverified'),
    ('mitochondrial_matrix', 'mitochondrial', 'R',
     'NCBI Genetic Codes, table 3; S. cerevisiae mtDNA gene content', 'unverified'),
    -- Both genomes, for the same reason: COX1/COB and friends are mtDNA-encoded, while most
    -- inner-membrane proteins are imported.
    ('mitochondrial_inner_membrane', 'nuclear', 'R',
     'NCBI Genetic Codes, table 3; S. cerevisiae mtDNA gene content', 'unverified'),
    ('mitochondrial_inner_membrane', 'mitochondrial', 'R',
     'NCBI Genetic Codes, table 3; S. cerevisiae mtDNA gene content', 'unverified');

-- Cofactor pools are pooled separately per compartment: a route that balances NADH globally can
-- still be unbalanced in the matrix, which is the whole point of the per-compartment check.
CREATE TABLE compartment_cofactor_pool (
    compartment_id TEXT NOT NULL REFERENCES compartment(id) ON DELETE CASCADE,
    cofactor       TEXT NOT NULL,           -- NADH | NADPH | ATP | CoA | ...
    notes          TEXT,
    zone           TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence       TEXT NOT NULL,
    confidence     TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high')),
    PRIMARY KEY (compartment_id, cofactor)
);


-- ---------------------------------------------------------------------------------------------
-- 4. Genes
-- ---------------------------------------------------------------------------------------------

-- The join key for everything cross-strain and cross-study (PLAN.md C.3). Raw `gene` rows are
-- never joined across assemblies.
CREATE TABLE gene_group (
    id                TEXT PRIMARY KEY,     -- YAA:GG:ygr192c
    anchor_namespace  TEXT,                 -- 'sgd_systematic' for yeast
    anchor_id         TEXT,                 -- YGR192C, when one exists
    standard_name     TEXT,                 -- TDH3
    scope             TEXT NOT NULL CHECK (scope IN ('species', 'genus', 'cross_species')),
    membership_method TEXT NOT NULL
                      CHECK (membership_method IN ('anchor', 'orthofinder', 'ygob', 'rbh',
                                                   'curated')),
    zone              TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence          TEXT NOT NULL,
    confidence        TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);

CREATE TABLE gene (
    id                  TEXT PRIMARY KEY,
    organism_id         TEXT NOT NULL REFERENCES organism(id),
    -- A gene id is meaningless without its assembly: genome-db found 520 ids shared between two
    -- assemblies while naming different genes. NOT NULL for that reason.
    assembly_accession  TEXT NOT NULL,
    systematic_name     TEXT,
    standard_name       TEXT,
    gene_group_id       TEXT REFERENCES gene_group(id),
    -- 0-based half-open [start_pos, end_pos). Length is end_pos - start_pos.
    start_pos           INTEGER,
    end_pos             INTEGER,
    strand              INTEGER CHECK (strand IN (-1, 0, 1)),
    zone                TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence            TEXT NOT NULL,
    confidence          TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high')),
    CHECK (start_pos IS NULL OR end_pos IS NULL OR end_pos > start_pos),
    UNIQUE (assembly_accession, id)
);


-- ---------------------------------------------------------------------------------------------
-- 5. Chemistry and products
-- ---------------------------------------------------------------------------------------------

-- v10. `tier` and `mw_g_mol` are columns because PLAN.md B.1 says the first one is: "the tier is a
-- stored property of `product` that drives the acquisition policy in code. It is not an informal
-- understanding." Until v10 it was exactly an informal understanding -- `products.tsv` has carried
-- `tier` as its FIRST column since the vocabulary was written, and `load_products` interpolated it
-- into a prose evidence sentence and dropped it. Nothing could filter on it, so no admission policy
-- could be enforced in code, which is the one thing B.1 asks of it.
--
-- `mw_g_mol` went the same way, and its loss is quantitative rather than procedural: B.6.7 rests on
-- isobutanol being more growth-inhibitory than ethanol *on a molar basis*, and a g/L titer cannot
-- be put on a molar axis without the molecular weight. The value was curated in
-- `products.tsv.product_mw_g_mol` and never landed, so every molar comparison would have had to
-- recompute it from the formula -- which is how a "computed from standard atomic weights,
-- unverified" number becomes indistinguishable from a cited one.
CREATE TABLE product (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    -- B.1's four tiers. NOT a free-text column: `adjacent` carries an admission rule that
    -- `curate.promote` enforces, and `reserved` marks the rows that prove the schema is
    -- product-generic (PLAN.md section U) and are expected to stay empty.
    tier           TEXT CHECK (tier IN ('primary', 'reference', 'adjacent', 'reserved')),
    mw_g_mol       REAL CHECK (mw_g_mol IS NULL OR mw_g_mol > 0),
    inchikey       TEXT,
    chebi_id       TEXT,
    formula        TEXT,
    carbon_number  INTEGER,
    canonical_unit TEXT,
    zone           TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence       TEXT NOT NULL,
    confidence     TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);

-- Theoretical yields are per (product, substrate) and cited, never computed on the fly: the
-- stoichiometry depends on the substrate, on the assumed pathway and on the assumed redox/ATP
-- closure (PLAN.md C.4). They drive the QC bound, so an uncited one would silently set a wrong
-- ceiling.
--
-- `substrate` is part of the PRIMARY KEY and is NOT NULL precisely so that glucose stops being an
-- unnamed assumption baked into a column name: 0.411 g/g for isobutanol is a statement about
-- glucose, and the same product on xylose or on glycerol is a different number entirely. A column
-- called `theoretical_yield_g_per_g` says "from something", which is not a quantity.
--
-- The three-state numeric rule of the file header applies here (`<col>_state`). "The stoichiometry
-- has been worked out and is 0.411" and "someone recorded that this product has a theoretical
-- yield but could not resolve it" and "nobody ever looked" are three different facts, and a bare
-- REAL column can only express one of them. The old CHECK (g_per_g > 0) made the middle state
-- unstorable, so positivity now applies only to a value that claims to be recorded.
CREATE TABLE product_theoretical_yield (
    product_id        TEXT NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    substrate         TEXT NOT NULL,        -- 'glucose' | 'xylose' | 'glycerol' | ...
    g_per_g           REAL,
    g_per_g_state     TEXT CHECK (g_per_g_state IN ('recorded', 'not_applicable', 'unknown')),
    mol_per_mol       REAL,
    mol_per_mol_state TEXT CHECK (mol_per_mol_state IN ('recorded', 'not_applicable', 'unknown')),
    stoichiometry     TEXT,
    zone              TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence          TEXT NOT NULL,
    confidence        TEXT NOT NULL
                      CHECK (confidence IN ('unverified', 'low', 'medium', 'high')),
    PRIMARY KEY (product_id, substrate),
    -- The numeric is present if and only if the state says 'recorded'. Both directions, so that
    -- neither a number filed as 'unknown' nor a 'recorded' state with nothing recorded can exist.
    CHECK (g_per_g IS NULL OR g_per_g_state = 'recorded'),
    CHECK (g_per_g_state <> 'recorded' OR (g_per_g IS NOT NULL AND g_per_g > 0)),
    CHECK (mol_per_mol IS NULL OR mol_per_mol_state = 'recorded'),
    CHECK (mol_per_mol_state <> 'recorded' OR (mol_per_mol IS NOT NULL AND mol_per_mol > 0))
);

-- v6 added `carbons`, `carrier`, `redox`, `pair` and `adenylate`. They were in
-- data/pathways/*.yaml and on metabolic/curated.py's dataclass from the start, were used by its
-- balance checks in memory, and were then dropped on the way in -- so the database could not tell
-- NADPH from acetolactate, and the reaction graph a UI reads could not put carriers on the edges
-- (PLAN.md P.2) or state the cofactor argument the DUET design turns on.
--
-- All five are nullable. A metabolite whose carrier status was never assessed is a different
-- thing from one known not to be a carrier, and an imported metabolite will have neither.
CREATE TABLE metabolite (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    inchikey   TEXT,
    chebi_id   TEXT,
    formula    TEXT,
    -- Carbons contributed to the *skeleton being tracked*, not the molecular formula: a carrier
    -- is 0 because it conserves its own carbon. See the header of the curated pathway files.
    carbons    INTEGER CHECK (carbons IS NULL OR carbons >= 0),
    carrier    INTEGER CHECK (carrier IN (0, 1)),
    -- The pool a redox carrier belongs to ('nad', 'nadp'), so the two halves of a couple can be
    -- matched. Declared before `redox`, which checks it -- see below.
    pair       TEXT,
    -- These two conditions are written as *column* CHECKs referring to sibling columns, rather
    -- than as separate table-level CHECKs, for one reason: SQLite has no ADD CONSTRAINT, so a
    -- table-level CHECK can never be reached by `ALTER TABLE ... ADD COLUMN`. A migrated database
    -- would have silently ended up with weaker constraints than a freshly created one, and
    -- `PRAGMA table_info` does not report CHECKs, so no shape comparison would have caught it.
    -- Column CHECKs may reference other columns of the same table and do survive the ALTER, so
    -- both routes now produce the same schema. tests/test_migrations.py checks this by behaviour.
    redox      TEXT CHECK (redox IS NULL
                           OR (redox IN ('reduced', 'oxidized')
                               AND pair IS NOT NULL
                               AND carrier = 1)),
    adenylate  TEXT CHECK (adenylate IS NULL
                           OR (adenylate IN ('charged', 'discharged') AND carrier = 1)),
    zone       TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence   TEXT NOT NULL,
    confidence TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);

CREATE TABLE reaction (
    id             TEXT PRIMARY KEY,
    name           TEXT,
    ec_number      TEXT,
    rhea_id        TEXT,
    equation       TEXT,
    -- A reaction without a compartment cannot be balanced per compartment, which is the gate
    -- that makes route enumeration meaningful (PLAN.md G.7).
    compartment_id TEXT REFERENCES compartment(id),
    reversible     INTEGER CHECK (reversible IN (0, 1)),
    -- v6. Whether this reaction competes with the pathway it sits in for a shared intermediate.
    -- data/pathways/*.yaml has carried it from the start and nothing wrote it, so which reactions
    -- drain the 2-ketoisovalerate pool -- the valine branch, the leucine branch, ECM31 -- was not
    -- a fact the database held. It is the most decision-relevant property of a curated pathway
    -- and a route ranker reads it.
    --
    -- Nullable on purpose: a reaction nobody has assessed is not a reaction known to be
    -- non-competing, and an imported reaction will be the former.
    competing      INTEGER CHECK (competing IN (0, 1)),
    zone           TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence       TEXT NOT NULL,
    confidence     TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);

-- v6. Which genes encode the enzyme that runs a reaction.
--
-- Before this, metabolic/curated.py appended them to the reaction's evidence sentence as
-- "[genes: LEU4, LEU9]" -- readable by a person, invisible to a query, and unjoinable to `gene`,
-- whose 36 resolved rows include most of them.
--
-- A junction row: it inherits the zone of its parent `reaction` and does not repeat the column.
--
-- `resolution` is a three-state column rather than an inference from `gene_id IS NULL`, because
-- NULL alone is ambiguous between "looked up and not found" and "never looked up". The
-- distinction is load-bearing here: CONVENTIONS.md forbids mapping an unresolved identifier to
-- the nearest plausible match, and the pathway files name ADH1, ADH6 and ADH7, none of which are
-- in `gene`. Recording those as unresolved is correct; quietly resolving them to ADH2 is the
-- exact failure the rule exists to prevent.
CREATE TABLE reaction_gene (
    reaction_id   TEXT NOT NULL REFERENCES reaction(id) ON DELETE CASCADE,
    -- Exactly as the curated file wrote it, and kept even when resolution succeeds: the
    -- as-written form is Zone R and the resolution is not.
    gene_symbol   TEXT NOT NULL,
    gene_id       TEXT REFERENCES gene(id),
    gene_group_id TEXT REFERENCES gene_group(id),
    resolution    TEXT NOT NULL
                  CHECK (resolution IN ('resolved', 'unresolved', 'not_attempted')),
    PRIMARY KEY (reaction_id, gene_symbol),
    -- 'resolved' must name something, and anything else must not, so a stale id cannot survive a
    -- downgrade to 'unresolved'.
    CHECK (resolution <> 'resolved' OR gene_id IS NOT NULL),
    CHECK (resolution = 'resolved' OR gene_id IS NULL)
);

CREATE INDEX reaction_gene_by_gene ON reaction_gene(gene_id);
CREATE INDEX reaction_gene_by_symbol ON reaction_gene(gene_symbol);

-- A junction row: it inherits the zone of its parent `reaction` and does not repeat the column.
CREATE TABLE reaction_participant (
    reaction_id   TEXT NOT NULL REFERENCES reaction(id) ON DELETE CASCADE,
    metabolite_id TEXT NOT NULL REFERENCES metabolite(id),
    role          TEXT NOT NULL CHECK (role IN ('substrate', 'product', 'cofactor')),
    -- Signed stoichiometric coefficient; 0 would be a balance-breaking silent no-op.
    coefficient   REAL NOT NULL CHECK (coefficient <> 0),
    PRIMARY KEY (reaction_id, metabolite_id, role)
);

CREATE TABLE pathway (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    product_id TEXT REFERENCES product(id),
    zone       TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence   TEXT NOT NULL,
    confidence TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);

-- A junction row: it inherits the zone of its parent `pathway` and does not repeat the column.
CREATE TABLE pathway_reaction (
    pathway_id   TEXT NOT NULL REFERENCES pathway(id) ON DELETE CASCADE,
    reaction_id  TEXT NOT NULL REFERENCES reaction(id),
    step_order   INTEGER NOT NULL,
    step_role_id TEXT REFERENCES step_role(id),
    PRIMARY KEY (pathway_id, reaction_id)
);


-- ---------------------------------------------------------------------------------------------
-- 6. Literature
-- ---------------------------------------------------------------------------------------------

CREATE TABLE publication (
    id         TEXT PRIMARY KEY,            -- doi:... or pmid:...
    doi        TEXT,
    pmid       TEXT,
    title      TEXT,
    year       INTEGER,
    journal    TEXT,
    -- Access terms decide whether full text may be stored at all (PLAN.md H.4).
    license    TEXT,
    zone       TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence   TEXT NOT NULL,
    confidence TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);

-- An extraction is always Zone I until a curator promotes it: it is model output about a paper,
-- not the paper. The CHECK makes that structural rather than a habit.
--
-- The column list is PLAN.md H.5's, filled out from the original stub when
-- src/fermdb/extract/harness.py was written. Section 14 ("Extraction and curation") is the other
-- half of the same story and explains the review_state lifecycle in full; read it with this.
CREATE TABLE extraction (
    id                TEXT PRIMARY KEY,
    publication_id    TEXT NOT NULL REFERENCES publication(id),
    -- Which sections of the paper the model was actually shown, comma-separated in document
    -- order. PLAN.md V.4 sends methods + results only, which is ~13x cheaper than whole text --
    -- and that makes this column load-bearing rather than decorative: "the model did not report
    -- X" means nothing unless you know whether it was shown the part of the paper X lives in.
    section           TEXT,
    extractor         TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    model             TEXT,
    -- What actually answered, which stops being the same as `model` the moment a tag is re-pulled.
    model_version     TEXT,
    -- The prompt file's declared version PLUS a digest of its bytes. An extraction is not
    -- reproducible without the prompt that produced it (PLAN.md L.3), and a prompt edited without
    -- a version bump would otherwise reuse an old version string over new text.
    prompt_version    TEXT,
    run_id            TEXT,
    -- The `input_hash` half of PLAN.md L.3's (input_hash, model, prompt_version) cache key, so a
    -- stored row can be traced back to the cached model call that produced it.
    input_hash        TEXT,
    -- The typed payload as JSON: strains, modifications, pathway_configurations, measurements,
    -- conditions, bottlenecks, co_reported_higher_alcohols (src/fermdb/extract/schemas.py).
    payload           TEXT,
    -- What the model said about its own certainty. Kept as an audit trail and READ BY NOTHING:
    -- docs/reference/MODEL_ROUTING.md 5.2 forbids model capability or self-report from entering
    -- the derivation of a confidence value. Every extracted value's confidence is 'unverified'.
    self_confidence   TEXT,
    -- The deterministic validator's report (fermdb.llm.validate): the non-fatal issues a curator
    -- should see. Fatally rejected records are not in `payload` at all -- they were never stored.
    validation        TEXT,
    -- PLAN.md H.5's lifecycle. 'proposed' is where every model output lands.
    review_state      TEXT NOT NULL DEFAULT 'proposed'
                      CHECK (review_state IN ('proposed', 'accepted', 'edited', 'rejected')),
    curator           TEXT,
    reviewed_at       TEXT,
    review_reason     TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    zone              TEXT NOT NULL DEFAULT 'I' CHECK (zone = 'I'),
    -- Leaving Zone I is a curator action (PLAN.md L.1, L.5). A row that claims to have been
    -- reviewed must name who reviewed it, when, and why, so a process cannot mark its own
    -- proposal accepted without leaving a name behind; and a row still 'proposed' must carry
    -- none of the three, so a half-filled review cannot masquerade as an unreviewed proposal.
    CHECK (review_state = 'proposed'
           OR (curator IS NOT NULL AND reviewed_at IS NOT NULL AND review_reason IS NOT NULL)),
    CHECK (review_state <> 'proposed'
           OR (curator IS NULL AND reviewed_at IS NULL AND review_reason IS NULL))
);

CREATE INDEX extraction_by_publication ON extraction(publication_id, review_state);

-- The exact text an extraction came from. 0-based half-open [char_start, char_end).
--
-- Offsets are into the WHOLE document, not into the methods+results excerpt the model was shown.
-- The harness verifies a span twice: once against the excerpt (the text the model actually saw,
-- which is what its offsets refer to) and again against the document after translating them.
-- A quote that survives only the first check is not storable.
CREATE TABLE span (
    id             TEXT PRIMARY KEY,
    publication_id TEXT NOT NULL REFERENCES publication(id),
    extraction_id  TEXT REFERENCES extraction(id),
    section        TEXT,
    char_start     INTEGER,
    char_end       INTEGER,
    quoted_text    TEXT,
    -- Which field of which record in the extraction's payload this span is the evidence for --
    -- 'measurements[0]', 'modifications[2]'. Without it a span is a quote attached to a whole
    -- extraction, and a curator reviewing one value cannot tell which quote justified it.
    record_path    TEXT,
    zone           TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    CHECK (char_start IS NULL OR char_end IS NULL OR char_end > char_start)
);

CREATE INDEX span_by_extraction ON span(extraction_id);


-- ---------------------------------------------------------------------------------------------
-- 7. Conditions, experiments, samples, measurements
-- ---------------------------------------------------------------------------------------------

-- Two rules from the file header are worked out in full here, because this is the table where
-- they bite:
--
-- THREE-STATE NUMERICS. Every numeric facet carries `<col>_state`. "30 degrees", "the paper says
-- the temperature was not controlled, so it is not applicable", "the paper mentions a temperature
-- it never states" and "nobody recorded anything" are four different facts; a bare REAL can hold
-- only the first and the last, and collapsing the middle two into NULL is exactly the coercion
-- CONVENTIONS.md forbids. The numeric is NULL unless its state is 'recorded'; numeric NULL with
-- state NULL means never recorded at all.
--
-- as_reported SHADOWS. A facet that is parsed out of prose carries `<facet>_as_reported`, holding
-- the source's verbatim string -- "30 +/- 1 C", "micro-aerobic (0.2 vvm)", "YPD + 2% glucose".
-- The parsed column is Zone H and is rebuilt by re-running the parser; the shadow is Zone R and
-- is never overwritten. Facets that are not parsed from prose (vessel_type, working_volume_l,
-- dilution_rate, time_h, scale_class, growth_phase) are read off a number or a single word and
-- use `condition_context_facet`, which has an as_reported column of its own, when the source's
-- wording matters. `completeness_score` is computed by the atlas, not reported, so it has neither
-- a shadow nor a state column.
--
-- Immutable and deduplicated by context_hash: identical conditions across papers share one row,
-- so a saved analysis can name the context it used and get the same rows back (PLAN.md C.5). The
-- hash covers the *recorded* facets, which now means the (value, state) pair -- two rows that
-- differ only in whether a missing pH was 'not_applicable' or 'unknown' are different contexts.
CREATE TABLE condition_context (
    id                   TEXT PRIMARY KEY,
    context_hash         TEXT NOT NULL UNIQUE,   -- stable hash over the *recorded* facets only

    medium_name          TEXT,
    medium_name_as_reported TEXT,
    medium_class         TEXT CHECK (medium_class IN ('defined', 'complex', 'industrial',
                                                      'NA', 'unknown')),
    medium_class_as_reported TEXT,

    carbon_source_main   TEXT,
    carbon_source_main_as_reported TEXT,
    total_sugar_g_l      REAL,
    total_sugar_g_l_state TEXT CHECK (total_sugar_g_l_state IN ('recorded', 'not_applicable',
                                                                'unknown')),
    total_sugar_g_l_as_reported TEXT,
    feedstock_class      TEXT CHECK (feedstock_class IN ('defined', 'molasses', 'hydrolysate',
                                                         'starch', 'other', 'NA', 'unknown')),
    feedstock_class_as_reported TEXT,
    nitrogen_source      TEXT,

    aeration_class       TEXT CHECK (aeration_class IN ('anaerobic', 'microaerobic',
                                                        'oxygen_limited', 'aerobic',
                                                        'NA', 'unknown')),
    aeration_class_as_reported TEXT,
    vvm                  REAL,
    vvm_state            TEXT CHECK (vvm_state IN ('recorded', 'not_applicable', 'unknown')),
    vvm_as_reported      TEXT,
    dissolved_oxygen_pct REAL CHECK (dissolved_oxygen_pct IS NULL
                                     OR (dissolved_oxygen_pct >= 0
                                         AND dissolved_oxygen_pct <= 100)),
    dissolved_oxygen_pct_state TEXT CHECK (dissolved_oxygen_pct_state IN ('recorded',
                                                                          'not_applicable',
                                                                          'unknown')),
    dissolved_oxygen_pct_as_reported TEXT,

    mode                 TEXT CHECK (mode IN ('batch', 'fed_batch', 'continuous',
                                              'repeated_batch', 'SSF', 'SHF', 'CBP',
                                              'immobilized', 'NA', 'unknown')),
    mode_as_reported     TEXT,
    dilution_rate        REAL,
    dilution_rate_state  TEXT CHECK (dilution_rate_state IN ('recorded', 'not_applicable',
                                                             'unknown')),

    temperature_c        REAL,
    temperature_c_state  TEXT CHECK (temperature_c_state IN ('recorded', 'not_applicable',
                                                             'unknown')),
    temperature_c_as_reported TEXT,
    ph                   REAL,
    ph_state             TEXT CHECK (ph_state IN ('recorded', 'not_applicable', 'unknown')),
    ph_as_reported       TEXT,
    -- A flag, but a three-state one for the same reason: "uncontrolled" and "not stated" are the
    -- two most common values in the literature and they are not the same claim.
    ph_controlled        INTEGER CHECK (ph_controlled IN (0, 1)),
    ph_controlled_state  TEXT CHECK (ph_controlled_state IN ('recorded', 'not_applicable',
                                                             'unknown')),
    ph_controlled_as_reported TEXT,

    vessel_type          TEXT CHECK (vessel_type IN ('shake_flask', 'serum_bottle', 'microplate',
                                                     'bioreactor', 'NA', 'unknown')),
    working_volume_l     REAL,
    working_volume_l_state TEXT CHECK (working_volume_l_state IN ('recorded', 'not_applicable',
                                                                  'unknown')),
    scale_class          TEXT,
    time_h               REAL,
    time_h_state         TEXT CHECK (time_h_state IN ('recorded', 'not_applicable', 'unknown')),
    growth_phase         TEXT,

    -- Fraction of the facets that matter for this product that were recorded. The primary
    -- metadata-quality signal and the usual reason a study is excluded from a meta-analysis.
    -- Computed by the atlas from the columns above, so it is neither reported nor three-state.
    completeness_score   REAL CHECK (completeness_score IS NULL
                                     OR (completeness_score >= 0 AND completeness_score <= 1)),
    zone                 TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence             TEXT NOT NULL,
    confidence           TEXT NOT NULL
                         CHECK (confidence IN ('unverified', 'low', 'medium', 'high')),

    -- Each numeric is present if and only if its state says 'recorded'. Stated in both directions
    -- so that neither a number filed as 'unknown' nor a 'recorded' state with no number survives.
    CHECK (total_sugar_g_l IS NULL OR total_sugar_g_l_state = 'recorded'),
    CHECK (total_sugar_g_l_state <> 'recorded' OR total_sugar_g_l IS NOT NULL),
    CHECK (vvm IS NULL OR vvm_state = 'recorded'),
    CHECK (vvm_state <> 'recorded' OR vvm IS NOT NULL),
    CHECK (dissolved_oxygen_pct IS NULL OR dissolved_oxygen_pct_state = 'recorded'),
    CHECK (dissolved_oxygen_pct_state <> 'recorded' OR dissolved_oxygen_pct IS NOT NULL),
    CHECK (dilution_rate IS NULL OR dilution_rate_state = 'recorded'),
    CHECK (dilution_rate_state <> 'recorded' OR dilution_rate IS NOT NULL),
    CHECK (temperature_c IS NULL OR temperature_c_state = 'recorded'),
    CHECK (temperature_c_state <> 'recorded' OR temperature_c IS NOT NULL),
    CHECK (ph IS NULL OR ph_state = 'recorded'),
    CHECK (ph_state <> 'recorded' OR ph IS NOT NULL),
    CHECK (ph_controlled IS NULL OR ph_controlled_state = 'recorded'),
    CHECK (ph_controlled_state <> 'recorded' OR ph_controlled IS NOT NULL),
    CHECK (working_volume_l IS NULL OR working_volume_l_state = 'recorded'),
    CHECK (working_volume_l_state <> 'recorded' OR working_volume_l IS NOT NULL),
    CHECK (time_h IS NULL OR time_h_state = 'recorded'),
    CHECK (time_h_state <> 'recorded' OR time_h IS NOT NULL)
);

-- The long tail: facets with no first-class column above, and the verbatim strings for the ones
-- whose parsed form lives there. The parsed `value` is Zone H; `as_reported` is Zone R.
--
-- This table holds a fact, so it carries a zone of its own rather than inheriting one: a facet
-- row can be a curator's reading (R), a parser's output (H) or a model's guess (I) while the
-- `condition_context` it hangs off is any of the three. `zone` describes `value`; `as_reported`
-- is Zone R by definition, because it is the source's own string.
CREATE TABLE condition_context_facet (
    context_id  TEXT NOT NULL REFERENCES condition_context(id) ON DELETE CASCADE,
    facet       TEXT NOT NULL,
    value       TEXT,                -- parsed, zone as per `zone` below
    -- A numeric facet stored here follows the same three-state rule as the columns above; `value`
    -- is TEXT, so 'NA' and 'unknown' are storable directly and `value_state` says which of the
    -- three a blank is.
    value_state TEXT CHECK (value_state IN ('recorded', 'not_applicable', 'unknown')),
    as_reported TEXT,                -- verbatim, always Zone R
    unit        TEXT,
    zone        TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence    TEXT NOT NULL,
    confidence  TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high')),
    PRIMARY KEY (context_id, facet),
    CHECK (value IS NULL OR value_state = 'recorded'),
    CHECK (value_state <> 'recorded' OR value IS NOT NULL)
);

CREATE TABLE experiment (
    id             TEXT PRIMARY KEY,
    publication_id TEXT REFERENCES publication(id),
    objective      TEXT,
    design_type    TEXT,
    zone           TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence       TEXT NOT NULL,
    confidence     TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);

CREATE TABLE dataset (
    id         TEXT PRIMARY KEY,
    accession  TEXT,                        -- insdc.sra:SRP..., geo:GSE...
    repository TEXT,
    omics_type TEXT,
    platform   TEXT,
    license    TEXT,
    zone       TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence   TEXT NOT NULL,
    confidence TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);

-- Provenance must reach the bytes, not just the accession: an accession can be revised, withdrawn
-- or silently re-deposited, and a checksum is the only thing that survives that.
CREATE TABLE raw_object (
    id           TEXT PRIMARY KEY,
    dataset_id   TEXT REFERENCES dataset(id),
    run_accession TEXT,                     -- insdc.sra:SRR...
    bucket       TEXT NOT NULL,
    object_key   TEXT NOT NULL,
    size_bytes   INTEGER CHECK (size_bytes IS NULL OR size_bytes >= 0),
    checksum_sha256 TEXT,
    retrieved_at TEXT,
    source_url   TEXT,
    media_type   TEXT,
    zone         TEXT NOT NULL DEFAULT 'R' CHECK (zone = 'R'),
    UNIQUE (bucket, object_key)
);

CREATE TABLE sample (
    id                   TEXT PRIMARY KEY,
    experiment_id        TEXT REFERENCES experiment(id),
    dataset_id           TEXT REFERENCES dataset(id),
    strain_id            TEXT REFERENCES strain(id),
    -- No sample enters a contrast without an approved condition context (CONVENTIONS.md).
    condition_context_id TEXT REFERENCES condition_context(id),
    time_h               REAL,
    growth_phase         TEXT,
    zone                 TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence             TEXT NOT NULL,
    confidence           TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);

-- Deliberately zone-less, and not an exemption by oversight: a processing_run is a record of a
-- computation having happened, not a claim about biology. Everything it produces carries a zone
-- of its own (analysis_result, pathway_route), and stamping one on the run would invite reading
-- the run itself as evidence.
CREATE TABLE processing_run (
    id               TEXT PRIMARY KEY,
    pipeline         TEXT NOT NULL,
    version          TEXT NOT NULL,
    container_digest TEXT,
    tool_versions    TEXT,                  -- JSON
    parameters_hash  TEXT,
    inputs_hash      TEXT,
    seed             INTEGER,
    started_at       TEXT,
    finished_at      TEXT,
    -- The producer's exit status, not only the consumer's success: a truncated input that still
    -- parses is the failure mode that matters.
    exit_status      INTEGER
);

CREATE TABLE analysis_result (
    id                TEXT PRIMARY KEY,
    processing_run_id TEXT NOT NULL REFERENCES processing_run(id),
    kind              TEXT NOT NULL,
    -- Points at Parquet on disk, never a BLOB in the database.
    payload_ref       TEXT NOT NULL,
    zone              TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I'))
);

-- Every quantitative experimental result, production and phenotype alike, is one row.
CREATE TABLE measurement (
    id                TEXT PRIMARY KEY,
    -- The subject, at whatever granularity was reported. At least one must be present, or the
    -- number belongs to nothing.
    sample_id         TEXT REFERENCES sample(id),
    strain_id         TEXT REFERENCES strain(id),
    experiment_id     TEXT REFERENCES experiment(id),
    -- The paper the number was read out of. Nullable, because a measurement derived from a
    -- deposited dataset rather than from a publication is a legitimate row -- but NULL here means
    -- "there is no paper", never "the paper is in the evidence sentence". PLAN.md J.5 wants a
    -- walkable chain assertion -> evidence_item -> measurement -> publication, and prose in
    -- `evidence` is not a join: `curate/assertions.py` could not close that last hop, and
    -- regexing a DOI back out of a sentence would produce a confidently wrong answer the first
    -- time the sentence's format changed.
    publication_id    TEXT REFERENCES publication(id),
    quantity_kind     TEXT NOT NULL,        -- titer | yield | productivity | growth_rate | ...
    product_id        TEXT REFERENCES product(id),   -- NULL for non-product quantities
    -- Zone R, never overwritten and never unit-converted in place. Enforced by the trigger below.
    value_as_reported REAL NOT NULL,
    unit_as_reported  TEXT NOT NULL,
    -- Zone H, derived. Written beside the reported value, with the rule recorded in derived_by.
    value_si          REAL,
    unit_si           TEXT,
    -- Mandatory for a yield: g/g-consumed and g/g-supplied are different numbers and papers
    -- report both without saying which. Where the paper does not state it the curator must write
    -- 'unknown' rather than leaving it blank, and an 'unknown' basis is not comparable across
    -- studies. NULL (never recorded) is therefore forbidden for a yield.
    basis             TEXT CHECK (basis IN ('consumed', 'supplied', 'theoretical_max_pct',
                                            'per_biomass', 'per_volume', 'NA', 'unknown')),
    -- The row declares whether it is a fraction; the constraint then holds it in [0, 1]. Declared
    -- per row rather than inferred from quantity_kind so that no product-specific list of "rate
    -- kinds" ever has to live in code.
    is_fraction       INTEGER NOT NULL DEFAULT 0 CHECK (is_fraction IN (0, 1)),
    assay_method      TEXT,                 -- HPLC | GC | enzymatic | gravimetric | OD | ...
    assay_details     TEXT,
    detection_limit   REAL,
    is_below_lod      INTEGER NOT NULL DEFAULT 0 CHECK (is_below_lod IN (0, 1)),
    is_upper_bound    INTEGER NOT NULL DEFAULT 0 CHECK (is_upper_bound IN (0, 1)),
    uncertainty_sd    REAL CHECK (uncertainty_sd IS NULL OR uncertainty_sd >= 0),
    uncertainty_sem   REAL CHECK (uncertainty_sem IS NULL OR uncertainty_sem >= 0),
    ci_low            REAL,
    ci_high           REAL,
    n_replicates      INTEGER CHECK (n_replicates IS NULL OR n_replicates >= 1),
    replicate_type    TEXT CHECK (replicate_type IN ('biological', 'technical', 'unknown')),
    -- NULL if the paper reported the number; otherwise the rule that computed it. A reported
    -- yield and one the atlas computed from titer and sugar consumed are both useful; conflating
    -- them is not.
    derived_by        TEXT,
    -- A value read off a figure is a different evidence grade from a tabulated one.
    is_digitized      INTEGER NOT NULL DEFAULT 0 CHECK (is_digitized IN (0, 1)),
    source_locator    TEXT NOT NULL,        -- 'table 2, row 3' | 'figure 4B' | 'text'
    zone              TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence          TEXT NOT NULL,
    confidence        TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high')),
    CHECK (sample_id IS NOT NULL OR strain_id IS NOT NULL OR experiment_id IS NOT NULL),
    CHECK (quantity_kind <> 'yield' OR basis IS NOT NULL),
    CHECK (is_fraction = 0
           OR (value_as_reported >= 0 AND value_as_reported <= 1
               AND (value_si IS NULL OR (value_si >= 0 AND value_si <= 1)))),
    CHECK (ci_low IS NULL OR ci_high IS NULL OR ci_high >= ci_low),
    -- A derived value must say which unit it is in, or it is just another bare number.
    CHECK (value_si IS NULL OR unit_si IS NOT NULL)
);

-- Zone R is append-only. A conversion writes value_si beside the reported value; it never edits
-- it. Without this trigger the rule is a comment, and comments do not survive a bulk update.
CREATE TRIGGER measurement_reported_value_is_immutable
BEFORE UPDATE OF value_as_reported, unit_as_reported ON measurement
FOR EACH ROW WHEN OLD.zone = 'R'
BEGIN
    SELECT RAISE(ABORT,
        'value_as_reported/unit_as_reported are Zone R and immutable; write value_si instead');
END;

CREATE INDEX measurement_by_strain ON measurement(strain_id);
CREATE INDEX measurement_by_sample ON measurement(sample_id);
CREATE INDEX measurement_by_product ON measurement(product_id, quantity_kind);
-- The J.5 direction of travel: given a paper, which numbers came out of it.
CREATE INDEX measurement_by_publication ON measurement(publication_id);


-- ---------------------------------------------------------------------------------------------
-- 8. Modifications: the engineering atlas
--
-- 'localization_change' and 'mtdna_edit' are two different things travelling under one name, and
-- merging them loses the distinction that decides what is buildable (ISOBUTANOL_PROGRAM.md 4.1
-- vs 4.2). Each therefore gets its own table with its own required fields. The composite foreign
-- key (modification_id, type) -> modification(id, type) makes it impossible to attach mtDNA-edit
-- fields to a localization change, or either to a deletion.
-- ---------------------------------------------------------------------------------------------

CREATE TABLE modification (
    id                 TEXT PRIMARY KEY,
    strain_id          TEXT REFERENCES strain(id),
    type               TEXT NOT NULL
                       CHECK (type IN ('deletion', 'overexpression', 'promoter_swap',
                                       'point_mutation', 'heterologous_insertion',
                                       'downregulation', 'localization_change', 'mtdna_edit',
                                       'other')),
    target_gene_group_id TEXT REFERENCES gene_group(id),
    target_locus       TEXT,
    source_organism_id TEXT REFERENCES organism(id),   -- for heterologous parts
    details            TEXT,
    publication_id     TEXT REFERENCES publication(id),
    zone               TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence           TEXT NOT NULL,
    confidence         TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high')),
    -- Needed as the target of the composite FK from the two subtype tables.
    UNIQUE (id, type)
);

-- A subtype row, not a fact of its own: it extends exactly one `modification` and inherits that
-- row's zone, evidence and confidence. Repeating them here would let the two disagree.
CREATE TABLE modification_localization_change (
    modification_id          TEXT PRIMARY KEY,
    -- Redundant by design: it is what lets the composite FK below pin the subtype.
    type                     TEXT NOT NULL DEFAULT 'localization_change'
                             CHECK (type = 'localization_change'),
    target_compartment_id    TEXT REFERENCES compartment(id),
    -- The genome the relocalized gene is expressed from, and therefore the code it is read by.
    -- A presequence-targeted construct is 'nuclear': it is translated on cytosolic ribosomes
    -- under table 1 and imported, so it needs NO recoding however mitochondrial its destination.
    -- Recoding such a construct for table 3 would mistranslate it. Default 'nuclear' because a
    -- localization_change is by definition an import event; an mtDNA-encoded gene is the other
    -- modification type (modification_mtdna_edit), not a relocalization.
    encoding_genome          TEXT NOT NULL DEFAULT 'nuclear' REFERENCES encoding_genome(id),
    targeting_sequence       TEXT,
    source_of_sequence       TEXT,
    cleavage_site_predicted  INTEGER,
    n_terminal_fusion_retained INTEGER CHECK (n_terminal_fusion_retained IN (0, 1)),
    -- NOT NULL with a default of 'none_reported'. A claimed relocalization with no localization
    -- evidence is common and consequential: the construct may simply not be imported, and every
    -- conclusion resting on it is then unsupported. A blank here would read as "fine".
    verification_method      TEXT NOT NULL DEFAULT 'none_reported'
                             CHECK (verification_method IN ('microscopy', 'fractionation',
                                                            'protease_protection',
                                                            'activity_in_fraction',
                                                            'none_reported')),
    import_efficiency_reported REAL CHECK (import_efficiency_reported IS NULL
                                           OR (import_efficiency_reported >= 0
                                               AND import_efficiency_reported <= 1)),
    FOREIGN KEY (modification_id, type) REFERENCES modification(id, type) ON DELETE CASCADE,
    FOREIGN KEY (target_compartment_id, encoding_genome)
        REFERENCES compartment_encoding_genome(compartment_id, encoding_genome)
);

-- A subtype row, on the same terms as modification_localization_change above: zone, evidence and
-- confidence live on the parent `modification`.
CREATE TABLE modification_mtdna_edit (
    modification_id      TEXT PRIMARY KEY,
    type                 TEXT NOT NULL DEFAULT 'mtdna_edit' CHECK (type = 'mtdna_edit'),
    technique            TEXT NOT NULL
                         CHECK (technique IN ('biolistic_transformation', 'mitoTALEN',
                                              'mitoZFN', 'base_editor', 'other')),
    recipient_state      TEXT CHECK (recipient_state IN ('rho0', 'rho_minus',
                                                         'rho_plus_heteroplasmic', 'unknown')),
    marker               TEXT,
    -- An ORF placed into mtDNA must be recoded for table 3, or a leucine-rich gene mistranslates
    -- extensively while still looking sensible. No encoding_genome column here: an mtDNA edit is
    -- 'mitochondrial' by definition, which is exactly why this flag applies to this table and not
    -- to modification_localization_change, where the gene stays nuclear and must NOT be recoded.
    recoded_for_table_3  INTEGER CHECK (recoded_for_table_3 IN (0, 1)),
    heteroplasmy_achieved REAL CHECK (heteroplasmy_achieved IS NULL
                                      OR (heteroplasmy_achieved >= 0
                                          AND heteroplasmy_achieved <= 1)),
    -- Stops the route ranker proposing an mtDNA edit as casually as a promoter swap.
    feasibility_rating   TEXT CHECK (feasibility_rating IN ('routine', 'specialist', 'frontier',
                                                            'not_demonstrated_in_organism')),
    -- "Is this technique possible at all" and "is it possible in this lab" are two different
    -- facts and the schema keeps them apart (MITOCHONDRIAL_PROGRAM.md section 4).
    available_here       INTEGER CHECK (available_here IN (0, 1)),
    labs_demonstrating   INTEGER CHECK (labs_demonstrating IS NULL OR labs_demonstrating >= 0),
    FOREIGN KEY (modification_id, type) REFERENCES modification(id, type) ON DELETE CASCADE
);

-- The catalogue of sites an mtDNA insert may target, with what each one costs. Distinct from
-- `mtdna_insertion` below, which records a proposed or performed EDIT: this is the menu, that is
-- the order. Loaded from data/mitochondria/activator_map.yaml.
--
-- Benchmark BM-MIT-004 asks "for a proposed insertion locus, return utr_source,
-- activator_required and displaced_gene", and until this table existed the atlas could not
-- answer it even though the map had been curated — the knowledge was in the repo and unreachable
-- from a query.
--
-- One row is not a gene: `intergenic_upstream_COX2` is a silent region carried by the Fox lab's
-- pPT24 plasmid, and an insert there borrows COX2's leader while displacing nothing. That row is
-- why `displaced_if_used` is nullable and why the comment below, which says inserting always
-- costs you a gene, is true only of the replacement route.
CREATE TABLE mtdna_locus (
    id                   TEXT PRIMARY KEY,
    locus                TEXT NOT NULL UNIQUE,
    encodes              TEXT,
    -- JSON array. NULL means "not recorded", never "none required": an insert designed against a
    -- locus with NULL here is exactly the failure BM-MIT-004 exists to catch, so absence and
    -- emptiness must not be spelled the same way.
    activators           TEXT,
    utr_source           TEXT,
    displaced_if_used    TEXT,
    respiration_retained_if_used INTEGER
                         CHECK (respiration_retained_if_used IN (0, 1)),
    rescue_available     TEXT CHECK (rescue_available IN ('none', 'nuclear_allotopic_copy',
                                                          'second_locus', 'other', 'unknown')),
    zone                 TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence             TEXT NOT NULL,
    confidence           TEXT NOT NULL
                         CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);

CREATE INDEX mtdna_locus_by_displacement ON mtdna_locus(displaced_if_used);

-- Yeast mitochondrial mRNAs are not translated generically: each needs nuclear-encoded
-- translational activators that recognize its own 5' leader, so an insert must sit behind an
-- existing gene's UTR at that gene's locus — and inserting therefore costs you the gene whose UTR
-- you borrowed (MITOCHONDRIAL_PROGRAM.md 2.1). That trade is a field, not a footnote.
CREATE TABLE mtdna_insertion (
    id                   TEXT PRIMARY KEY,
    modification_id      TEXT NOT NULL
                         REFERENCES modification_mtdna_edit(modification_id) ON DELETE CASCADE,
    locus                TEXT NOT NULL,     -- COX2 | COX3 | COB | intergenic | ...
    utr_source           TEXT,              -- which gene's 5' leader drives it
    activator_required   TEXT,              -- Pet111 | Pet494/54/122 | ...
    displaced_gene       TEXT,              -- NULL = nothing displaced
    respiration_retained INTEGER CHECK (respiration_retained IN (0, 1)),
    rescue_strategy      TEXT CHECK (rescue_strategy IN ('none', 'nuclear_allotopic_copy',
                                                         'second_locus', 'other', 'unknown')),
    zone                 TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence             TEXT NOT NULL,
    confidence           TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);


-- ---------------------------------------------------------------------------------------------
-- 9. Parts catalog, configurations, routes
-- ---------------------------------------------------------------------------------------------

CREATE TABLE part (
    id                      TEXT PRIMARY KEY,
    step_role_id            TEXT NOT NULL REFERENCES step_role(id),
    source_organism_id      TEXT REFERENCES organism(id),
    gene_group_id           TEXT REFERENCES gene_group(id),
    sequence                TEXT,
    -- Every stored sequence names BOTH the compartment it is destined for and the genome that
    -- encodes it, because the genome is what fixes the genetic code the sequence is written in
    -- (section 3). The same ORF targeted to the matrix by a presequence (nuclear, table 1) and
    -- integrated into mtDNA (mitochondrial, table 3) are two different sequences, and the
    -- compartment alone cannot tell them apart. A sequence with no declared code cannot be
    -- validated by the recoder, which is why the CHECK below demands both.
    sequence_compartment_id TEXT REFERENCES compartment(id),
    sequence_encoding_genome TEXT REFERENCES encoding_genome(id),
    variant_of              TEXT REFERENCES part(id),
    cofactor_preference     TEXT CHECK (cofactor_preference IN ('NADH', 'NADPH', 'either',
                                                                'NA', 'unknown')),
    engineered_switch       INTEGER CHECK (engineered_switch IN (0, 1)),
    -- Matters for DHAD-class [Fe-S] enzymes: oxygen lability changes which routes are viable.
    oxygen_sensitivity      TEXT,
    zone                    TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence                TEXT NOT NULL,
    confidence              TEXT NOT NULL
                            CHECK (confidence IN ('unverified', 'low', 'medium', 'high')),
    CHECK (sequence IS NULL
           OR (sequence_compartment_id IS NOT NULL AND sequence_encoding_genome IS NOT NULL)),
    -- Makes an impossible pairing unstorable: there is no such thing as a mitochondrially-encoded
    -- cytosolic protein, and a row claiming one would send the recoder to the wrong table.
    FOREIGN KEY (sequence_compartment_id, sequence_encoding_genome)
        REFERENCES compartment_encoding_genome(compartment_id, encoding_genome)
);

-- One row per host x compartment actually demonstrated. "Works in E. coli" and "works in the
-- yeast mitochondrial matrix" are different facts and the catalog refuses to merge them.
CREATE TABLE part_expression_record (
    id                    TEXT PRIMARY KEY,
    part_id               TEXT NOT NULL REFERENCES part(id) ON DELETE CASCADE,
    host_strain_id        TEXT REFERENCES strain(id),
    compartment_id        TEXT REFERENCES compartment(id),
    -- "Expressed in the matrix" means two different experiments depending on which genome carried
    -- the gene, and `codon_optimized` is unreadable without it: optimized for which code?
    encoding_genome       TEXT REFERENCES encoding_genome(id),
    codon_optimized       INTEGER CHECK (codon_optimized IN (0, 1)),
    promoter              TEXT,
    expressed_ok          TEXT CHECK (expressed_ok IN ('yes', 'no', 'partial', 'unknown')),
    -- Distinct from expressed_ok: a band on a gel is not activity.
    activity_measured     TEXT CHECK (activity_measured IN ('yes', 'no', 'unknown')),
    outcome_measurement_id TEXT REFERENCES measurement(id),
    publication_id        TEXT REFERENCES publication(id),
    zone                  TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence              TEXT NOT NULL,
    confidence            TEXT NOT NULL
                          CHECK (confidence IN ('unverified', 'low', 'medium', 'high')),
    FOREIGN KEY (compartment_id, encoding_genome)
        REFERENCES compartment_encoding_genome(compartment_id, encoding_genome)
);

CREATE TABLE pathway_configuration (
    id                      TEXT PRIMARY KEY,
    name                    TEXT NOT NULL,
    pathway_id              TEXT REFERENCES pathway(id),
    product_id              TEXT REFERENCES product(id),
    -- FK into the seeded vocabulary rather than an inline CHECK list, so that adding a strategy
    -- for another product is a data change and not a code change.
    compartment_strategy_id TEXT REFERENCES compartment_strategy(id),
    host_strain_id          TEXT REFERENCES strain(id),
    description             TEXT,
    zone                    TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence                TEXT NOT NULL,
    confidence              TEXT NOT NULL
                            CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);

-- Enumeration is generative, not a catalogue of published builds: that is what lets "what has
-- never been tried" be answered as the complement of the evidence. An enumerated route is
-- therefore Zone H or Zone I and never Zone R.
-- v7. The chassis, as a set of properties rather than a name.
--
-- `ISOBUTANOL_PROGRAM.md` §6 defines this and nothing implemented it, so every enumerated route
-- was ranked against no chassis at all -- a generic answer to a specific question. The fields are
-- exactly §6's table plus the two the owner's M3 and M4 answers created.
--
-- Nearly everything is nullable, and that is the point: a profile is filled in over time, and
-- "not measured" has to be storable and distinguishable from "measured as zero". Numeric facets
-- carry their `<col>_state` companion per the file header's three-state rule.
CREATE TABLE chassis_profile (
    id                  TEXT PRIMARY KEY,
    -- A profile can exist before the strain row does: the owner knows their chassis long before
    -- a curated `strain` row is promoted for it.
    strain_id           TEXT REFERENCES strain(id),
    name_as_reported    TEXT NOT NULL,
    organism_id         TEXT REFERENCES organism(id),
    -- Editing scale. DUET names ~15 loci; in a polyploid the verification burden scales with
    -- this even where marker-free multiplex keeps the transformation count flat.
    ploidy              INTEGER CHECK (ploidy IS NULL OR ploidy >= 1),
    ploidy_state        TEXT CHECK (ploidy_state IN ('recorded', 'not_applicable', 'unknown')),
    -- v8. The ploidies NOT YET EXCLUDED, as a JSON array, for a chassis whose ploidy is unknown.
    --
    -- Requested by the owner 2026-09-21: "for ploidy keep all options in hand to choose in
    -- future". A single NULL would say only "unknown" and lose the useful half -- which is that
    -- the consequences differ per candidate and can be costed now. So the range is carried and
    -- the edit burden is reported as a span rather than a number.
    --
    -- These are candidates, not measurements: each is a value no evidence has ruled out. When
    -- one is measured it goes in `ploidy` with ploidy_state='recorded' and this column stops
    -- mattering.
    ploidy_candidates   TEXT,
    marker_free_multiplex INTEGER CHECK (marker_free_multiplex IN (0, 1)),
    -- Whether mitochondrial work is possible at all. A rho-zero chassis disqualifies a matrix
    -- pathway outright rather than merely costing it.
    rho_status          TEXT CHECK (rho_status IN ('rho_plus', 'rho_zero', 'rho_minus',
                                                   'unknown')),
    -- DUET requires Pdc-POSITIVE (DUET_TARGET.md §5.1): the ethanol-acetaldehyde shuttle is the
    -- mechanism, not the competition.
    pdc_status          TEXT CHECK (pdc_status IN ('intact', 'attenuated', 'minus', 'unknown')),
    ferments_xylose     INTEGER CHECK (ferments_xylose IN (0, 1)),
    -- M3, 2026-09-21. 'preferred' is the owner's answer: not required for discovery, preferred
    -- for production, overridable by a demonstrated and scalable process advantage.
    respiration_policy  TEXT CHECK (respiration_policy IN ('required', 'preferred',
                                                           'not_required', 'unknown')),
    -- M4, 2026-09-21. 'not_measured' is distinct from 0: a gap, not a limitation.
    resolves_higher_alcohol_panel INTEGER
                        CHECK (resolves_higher_alcohol_panel IN (0, 1)),
    higher_alcohol_panel_state TEXT
                        CHECK (higher_alcohol_panel_state IN ('recorded', 'not_measured')),
    -- Caps the useful titre. While NULL, every route's ceiling line reads "toxicity-limited ~X".
    isobutanol_tolerance_g_l REAL CHECK (isobutanol_tolerance_g_l IS NULL
                                         OR isobutanol_tolerance_g_l >= 0),
    isobutanol_tolerance_state TEXT
                        CHECK (isobutanol_tolerance_state IN ('recorded', 'not_applicable',
                                                              'unknown')),
    tolerance_endpoint  TEXT,            -- 'growth rate 50% of control' | 'viability' | ...
    -- Strategy E tooling. M2: not in hand, purchasable in a lab background only.
    mtdna_tooling       TEXT CHECK (mtdna_tooling IN ('available_here',
                                                      'available_after_acquisition',
                                                      'available_after_strain_construction',
                                                      'unavailable', 'unknown')),
    is_selected         INTEGER NOT NULL DEFAULT 0 CHECK (is_selected IN (0, 1)),
    zone                TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence            TEXT NOT NULL,
    confidence          TEXT NOT NULL
                        CHECK (confidence IN ('unverified', 'low', 'medium', 'high')),
    CHECK (ploidy IS NULL OR ploidy_state = 'recorded'),
    CHECK (isobutanol_tolerance_g_l IS NULL OR isobutanol_tolerance_state = 'recorded')
);

-- Exactly one chassis may be the selected one; the ranker scores against it.
CREATE UNIQUE INDEX chassis_profile_one_selected
    ON chassis_profile(is_selected) WHERE is_selected = 1;

CREATE TABLE pathway_route (
    id                       TEXT PRIMARY KEY,
    pathway_configuration_id TEXT REFERENCES pathway_configuration(id),
    host_strain_id           TEXT REFERENCES strain(id),
    cofactor_strategy        TEXT,
    deletion_set             TEXT,           -- JSON list of gene_group ids
    -- Score components are stored separately and shown separately. A single opaque number cannot
    -- be explained, and an unexplainable rank is not a decision aid (PLAN.md G.7).
    score_balance            REAL,
    score_evidence           REAL,
    score_feasibility        REAL,
    score_transport          REAL,
    score_toxicity           REAL,
    balance_status           TEXT CHECK (balance_status IN ('pass', 'fail', 'not_evaluated')),
    processing_run_id        TEXT REFERENCES processing_run(id),
    zone                     TEXT NOT NULL CHECK (zone IN ('H', 'I'))
);

-- A junction row: it inherits its parent route's zone (H or I) and does not repeat the column.
CREATE TABLE pathway_route_step (
    route_id       TEXT NOT NULL REFERENCES pathway_route(id) ON DELETE CASCADE,
    step_order     INTEGER NOT NULL,
    step_role_id   TEXT NOT NULL REFERENCES step_role(id),
    part_id        TEXT REFERENCES part(id),
    -- A route is { step -> part } x (compartment, encoding genome) assignment. The compartment
    -- alone does not specify the step: the cofactor pool depends on the compartment, but the
    -- genetic code depends on the genome, and "KDC in the matrix" is strategy C when it is
    -- nuclear-encoded and strategy E when it is carried on mtDNA -- different builds, different
    -- feasibility, different sequence. NOT NULL, with no default, because a route that declines
    -- to say which one it means is the ambiguity this schema exists to refuse.
    compartment_id TEXT NOT NULL REFERENCES compartment(id),
    encoding_genome TEXT NOT NULL REFERENCES encoding_genome(id),
    PRIMARY KEY (route_id, step_order),
    FOREIGN KEY (compartment_id, encoding_genome)
        REFERENCES compartment_encoding_genome(compartment_id, encoding_genome)
);


-- ---------------------------------------------------------------------------------------------
-- 10. Assertions and evidence
-- ---------------------------------------------------------------------------------------------

-- The unit of knowledge. An assertion is never edited: a revision supersedes it and both remain,
-- which is what makes "what did the atlas say last March" answerable.
CREATE TABLE assertion (
    id              TEXT PRIMARY KEY,
    subject_type    TEXT NOT NULL CHECK (subject_type IN ('gene_group', 'gene', 'strain',
                                                          'reaction', 'pathway', 'modification',
                                                          'part', 'metabolite', 'product',
                                                          'compartment', 'pathway_route')),
    subject_id      TEXT NOT NULL,          -- polymorphic; see header note
    predicate       TEXT NOT NULL REFERENCES predicate(id),
    object_type     TEXT NOT NULL CHECK (object_type IN ('gene_group', 'gene', 'strain',
                                                         'reaction', 'pathway', 'product',
                                                         'metabolite', 'compartment', 'part',
                                                         'literal')),
    object_id       TEXT,
    object_literal  TEXT,
    object_unit     TEXT,
    context_id      TEXT REFERENCES condition_context(id),
    product_id      TEXT REFERENCES product(id),
    direction       TEXT CHECK (direction IN ('increases', 'decreases', 'no_effect',
                                              'required_for', 'not_required')),
    effect_size     REAL,
    effect_unit     TEXT,
    effect_ci_low   REAL,
    effect_ci_high  REAL,
    effect_n        INTEGER CHECK (effect_n IS NULL OR effect_n >= 1),
    -- NOTE: there is deliberately no `level` column. The level is derived from the evidence by
    -- the assertion_level view below. A stored level silently becomes a lie the first time a new
    -- paper lands.
    level_override  TEXT CHECK (level_override IN ('L1', 'L2', 'L3', 'L4', 'L5')),
    override_reason TEXT,
    override_curator TEXT,
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'superseded', 'disputed', 'retracted')),
    supersedes_id   TEXT REFERENCES assertion(id),
    created_by_kind TEXT NOT NULL CHECK (created_by_kind IN ('curator', 'pipeline', 'agent')),
    created_by      TEXT NOT NULL,          -- curator name, pipeline id, or model@version
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    zone            TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence        TEXT NOT NULL,
    confidence      TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high')),
    -- An override requires a reason and a curator, and is displayed as an override. Without both
    -- it is indistinguishable from a judgement made by nobody.
    CHECK (level_override IS NULL
           OR (override_reason IS NOT NULL AND override_curator IS NOT NULL)),
    -- A literal object must carry its literal; a typed object must carry its id.
    CHECK (CASE WHEN object_type = 'literal'
                THEN object_literal IS NOT NULL AND object_id IS NULL
                ELSE object_id IS NOT NULL END),
    CHECK (supersedes_id IS NULL OR supersedes_id <> id)
);

CREATE INDEX assertion_by_subject ON assertion(subject_type, subject_id);
CREATE INDEX assertion_by_predicate ON assertion(predicate);

-- Per-evidence-type CHECK constraints, so a row that lies about what kind of evidence it is
-- cannot be written (PLAN.md J.3). This is genome-db's per-tier GRN discipline applied to the
-- evidence layer.
CREATE TABLE evidence_item (
    id                  TEXT PRIMARY KEY,
    assertion_id        TEXT NOT NULL REFERENCES assertion(id) ON DELETE CASCADE,
    evidence_type       TEXT NOT NULL
                        CHECK (evidence_type IN ('direct_perturbation', 'direct_biochemical',
                                                 'correlative_omics', 'comparative_genomic',
                                                 'computational_model', 'literature_assertion',
                                                 'ai_inference')),
    direction           TEXT CHECK (direction IN ('increases', 'decreases', 'no_effect',
                                                  'required_for', 'not_required')),
    -- Axis 2 of PLAN.md J.3: independence is counted by *group*, not by publication, because one
    -- group publishing three times is not three independent observations.
    independent_group   TEXT,
    publication_id      TEXT REFERENCES publication(id),
    span_id             TEXT REFERENCES span(id),

    -- direct_perturbation
    strain_id           TEXT REFERENCES strain(id),
    control_strain_id   TEXT REFERENCES strain(id),
    control_condition_id TEXT REFERENCES condition_context(id),

    -- direct_perturbation | direct_biochemical
    measurement_id      TEXT REFERENCES measurement(id),
    assay_method        TEXT,

    -- correlative_omics
    contrast_id         TEXT,
    analysis_result_id  TEXT REFERENCES analysis_result(id),
    effect_size         REAL,
    p_adjusted          REAL CHECK (p_adjusted IS NULL
                                    OR (p_adjusted >= 0 AND p_adjusted <= 1)),

    -- comparative_genomic
    variant_or_gene_set TEXT,
    strain_set          TEXT,
    statistic           REAL,

    -- computational_model
    model_id            TEXT,
    processing_run_id   TEXT REFERENCES processing_run(id),

    -- ai_inference (model_version is shared with computational_model)
    model               TEXT,
    model_version       TEXT,
    prompt_version      TEXT,
    review_state        TEXT CHECK (review_state IN ('pending', 'accepted', 'rejected')),
    extraction_id       TEXT REFERENCES extraction(id),

    eco_id              TEXT,               -- Evidence and Conclusion Ontology, for export
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'superseded', 'retracted')),
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    zone                TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence            TEXT NOT NULL,
    confidence          TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high')),

    -- Required fields per evidence_type. ELSE 0 makes an unlisted type unstorable, so adding a
    -- type forces a decision about what it must carry.
    CONSTRAINT evidence_item_required_fields CHECK (
        CASE evidence_type
            WHEN 'direct_perturbation' THEN
                strain_id IS NOT NULL
                AND (control_strain_id IS NOT NULL OR control_condition_id IS NOT NULL)
                AND measurement_id IS NOT NULL
                AND direction IS NOT NULL
            WHEN 'direct_biochemical' THEN
                assay_method IS NOT NULL AND measurement_id IS NOT NULL
            WHEN 'correlative_omics' THEN
                (contrast_id IS NOT NULL OR analysis_result_id IS NOT NULL)
                AND effect_size IS NOT NULL AND p_adjusted IS NOT NULL
            WHEN 'comparative_genomic' THEN
                variant_or_gene_set IS NOT NULL AND strain_set IS NOT NULL
                AND statistic IS NOT NULL
            WHEN 'computational_model' THEN
                model_id IS NOT NULL AND model_version IS NOT NULL
                AND processing_run_id IS NOT NULL
            WHEN 'literature_assertion' THEN
                publication_id IS NOT NULL AND span_id IS NOT NULL
            WHEN 'ai_inference' THEN
                model IS NOT NULL AND model_version IS NOT NULL
                AND prompt_version IS NOT NULL AND review_state IS NOT NULL
                -- THE constraint: an AI inference is structurally prevented from masquerading as
                -- a measurement. Deliberately restated here as well as in the exclusivity rule
                -- below, because it is the one that matters most and should survive an edit to
                -- either constraint.
                AND measurement_id IS NULL
            ELSE 0
        END
    ),
    -- Exclusivity: only the two direct types may cite a measurement at all. Without this, a
    -- correlative or literature row could quietly acquire the authority of a measured number.
    CONSTRAINT evidence_item_measurement_only_direct CHECK (
        measurement_id IS NULL
        OR evidence_type IN ('direct_perturbation', 'direct_biochemical')
    ),
    -- An AI inference is Zone I by definition. Promotion writes a new curated assertion citing
    -- it; it does not relabel this row.
    CONSTRAINT evidence_item_ai_inference_is_zone_i CHECK (
        evidence_type <> 'ai_inference' OR zone = 'I'
    )
);

CREATE INDEX evidence_item_by_assertion ON evidence_item(assertion_id, evidence_type);

-- Conflicts are first-class and recorded in both directions. Membership is a table rather than a
-- list column precisely so that "both directions" is structural: there is no first assertion.
CREATE TABLE conflict (
    id                 TEXT PRIMARY KEY,
    kind               TEXT NOT NULL CHECK (kind IN ('direction', 'magnitude', 'presence',
                                                     'identity')),
    -- The facets that differ between the conflicting studies. The most common real resolution is
    -- explained_by_context, and capturing the difference is worth more than declaring a winner.
    context_difference TEXT,
    status             TEXT NOT NULL DEFAULT 'open'
                       CHECK (status IN ('open', 'explained_by_context', 'resolved',
                                         'irreconcilable')),
    resolution_note    TEXT,
    curator            TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    zone               TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    CHECK (status = 'open' OR resolution_note IS NOT NULL)
);

-- A junction row: membership in a conflict, inheriting the conflict's zone.
CREATE TABLE conflict_member (
    conflict_id  TEXT NOT NULL REFERENCES conflict(id) ON DELETE CASCADE,
    assertion_id TEXT NOT NULL REFERENCES assertion(id) ON DELETE CASCADE,
    PRIMARY KEY (conflict_id, assertion_id)
);

-- The audit log of every curation decision. Section 15 below drives it for the extraction queue;
-- `claim`, `release`, `accept` and `edit` were added to `action` there.
CREATE TABLE curation_event (
    id          TEXT PRIMARY KEY,
    curator     TEXT NOT NULL,
    -- 'human' or 'agent'. A background curation worker is an agent: it may claim a task, release
    -- one, and comment. It may not accept, edit or promote -- PLAN.md L.5, "no agent may promote
    -- its own proposal". The CHECK at the foot of this table makes that a property of the
    -- database rather than a rule some Python function is trusted to remember.
    actor_kind  TEXT NOT NULL DEFAULT 'human' CHECK (actor_kind IN ('human', 'agent')),
    action      TEXT NOT NULL CHECK (action IN ('create', 'claim', 'release', 'accept', 'edit',
                                                'promote', 'reject', 'supersede',
                                                'override_level', 'resolve_conflict', 'comment')),
    target_type TEXT NOT NULL,
    target_id   TEXT NOT NULL,              -- polymorphic; see header note
    -- A rejection is recorded, not deleted: a rejected extraction that keeps being re-proposed
    -- is a signal about the model, and throwing it away loses that signal.
    rationale   TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    zone        TEXT NOT NULL DEFAULT 'R' CHECK (zone = 'R'),
    CHECK (action NOT IN ('accept', 'edit', 'promote') OR actor_kind = 'human')
);

CREATE INDEX curation_event_by_target ON curation_event(target_type, target_id, created_at);


-- ---------------------------------------------------------------------------------------------
-- 11. Gaps and bottlenecks
-- ---------------------------------------------------------------------------------------------

-- The atlas must be able to store "this step is required and we do not know how it happens" as a
-- row, not as an absence. An absent row is indistinguishable from an unfinished import.
CREATE TABLE knowledge_gap (
    id             TEXT PRIMARY KEY,
    kind           TEXT NOT NULL CHECK (kind IN ('transport_carrier_unknown',
                                                 'enzyme_unidentified', 'mechanism_unknown',
                                                 'quantitative_value_missing',
                                                 'never_attempted')),
    route_id       TEXT REFERENCES pathway_route(id),
    step_role_id   TEXT REFERENCES step_role(id),
    compartment_id TEXT REFERENCES compartment(id),
    description    TEXT NOT NULL,
    why_it_matters TEXT,
    status         TEXT NOT NULL DEFAULT 'open'
                   CHECK (status IN ('open', 'candidate_proposed', 'resolved')),
    zone           TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence       TEXT NOT NULL,
    confidence     TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);

-- A bottleneck is an assertion with a required shape, so that it cannot be recorded as a vague
-- opinion (PLAN.md G.8).
CREATE TABLE bottleneck (
    id                TEXT PRIMARY KEY,
    assertion_id      TEXT REFERENCES assertion(id),
    reaction_id       TEXT REFERENCES reaction(id),
    transport_step    TEXT,
    node              TEXT,
    route_context_id  TEXT REFERENCES pathway_configuration(id),
    -- Same reasoning as `measurement.publication_id`, and the same gap: a promoted bottleneck
    -- named its paper only inside `evidence`, while `bottleneck_fix_attempt` two tables down has
    -- carried a real `publication_id` all along. Nullable, because a bottleneck inferred from the
    -- curated pathway model rather than from a paper has no publication to name.
    publication_id    TEXT REFERENCES publication(id),
    observation_type  TEXT NOT NULL
                      CHECK (observation_type IN ('metabolite_accumulation', 'flux_measurement',
                                                  'overexpression_relieved', 'deletion_worsened',
                                                  'in_vitro_kinetics', 'inferred')),
    recurrence        INTEGER CHECK (recurrence IS NULL OR recurrence >= 0),
    zone              TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence          TEXT NOT NULL,
    confidence        TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high')),
    -- Name what is bottlenecked, or the row says nothing.
    CHECK (reaction_id IS NOT NULL OR transport_step IS NOT NULL OR node IS NOT NULL)
);

CREATE INDEX bottleneck_by_publication ON bottleneck(publication_id);

-- The highest-value field in the schema for the user's actual goal: it converts "2-KIV supply is
-- limiting" from folklore into a record of what people did about it and whether it helped.
CREATE TABLE bottleneck_fix_attempt (
    id             TEXT PRIMARY KEY,
    bottleneck_id  TEXT NOT NULL REFERENCES bottleneck(id) ON DELETE CASCADE,
    intervention   TEXT NOT NULL,
    outcome        TEXT NOT NULL CHECK (outcome IN ('worked', 'partial', 'no_effect', 'worse',
                                                    'unknown')),
    measurement_id TEXT REFERENCES measurement(id),
    publication_id TEXT REFERENCES publication(id),
    zone           TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence       TEXT NOT NULL,
    confidence     TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);


-- ---------------------------------------------------------------------------------------------
-- 12. The derived evidence level
--
-- PLAN.md J.3. This is a view and not a column: evidence accumulates continuously, and a stored
-- level is a lie the moment a new paper lands. The view recomputes on every read; if that ever
-- becomes too slow it is replaced by a materialized table refreshed on evidence change, never by
-- a hand-maintained column.
--
-- Only `status = 'active'` evidence counts. A retracted paper stops supporting its conclusion.
-- ---------------------------------------------------------------------------------------------

CREATE VIEW assertion_level AS
SELECT
    a.id AS assertion_id,
    counts.n_evidence,
    counts.n_direct,
    counts.n_direct_groups,
    counts.n_assoc_pubs,
    CASE
        WHEN counts.n_evidence = 0 THEN NULL
        -- Direct evidence exists but an open direction conflict is unresolved. L1 requires "no
        -- unresolved discordance", so this is deliberately NOT graded rather than downgraded:
        -- the honest answer is that the atlas does not yet know.
        WHEN counts.n_direct > 0 AND counts.n_open_direction_conflicts > 0 THEN NULL
        -- L2: L1 criteria met by >= 2 independent groups, concordant in direction.
        WHEN counts.n_direct > 0
             AND counts.n_direct_groups >= 2
             AND counts.n_direct_directions <= 1 THEN 'L2'
        -- L1: >= 1 direct_perturbation or direct_biochemical. The stated control and the
        -- measurement are already guaranteed by evidence_item's per-type CHECK, so there is
        -- nothing left to re-check here.
        WHEN counts.n_direct > 0 THEN 'L1'
        -- L3: no direct evidence, but concordant association across >= 3 independent studies.
        WHEN counts.n_assoc_pubs >= 3 AND counts.n_assoc_directions <= 1 THEN 'L3'
        -- L4: computational_model only.
        WHEN counts.n_model > 0 AND counts.n_assoc_pubs = 0 AND counts.n_weak = 0 THEN 'L4'
        -- L5: hypothesis. Also the floor for any evidence combination that reaches no higher
        -- rule, so that every assertion with evidence gets a level rather than a NULL hole.
        ELSE 'L5'
    END AS derived_level,
    a.level_override,
    a.override_reason,
    a.override_curator,
    CASE WHEN a.level_override IS NOT NULL THEN 1 ELSE 0 END AS is_overridden,
    -- The override is applied on top of the derived level and is always displayed as an override.
    COALESCE(
        a.level_override,
        CASE
            WHEN counts.n_evidence = 0 THEN NULL
            WHEN counts.n_direct > 0 AND counts.n_open_direction_conflicts > 0 THEN NULL
            WHEN counts.n_direct > 0
                 AND counts.n_direct_groups >= 2
                 AND counts.n_direct_directions <= 1 THEN 'L2'
            WHEN counts.n_direct > 0 THEN 'L1'
            WHEN counts.n_assoc_pubs >= 3 AND counts.n_assoc_directions <= 1 THEN 'L3'
            WHEN counts.n_model > 0 AND counts.n_assoc_pubs = 0 AND counts.n_weak = 0 THEN 'L4'
            ELSE 'L5'
        END
    ) AS level,
    CASE
        WHEN counts.n_evidence = 0 THEN 'no_evidence'
        WHEN counts.n_direct > 0 AND counts.n_open_direction_conflicts > 0
            THEN 'direct_evidence_discordant'
        WHEN counts.n_direct > 0
             AND counts.n_direct_groups >= 2
             AND counts.n_direct_directions <= 1 THEN 'direct_evidence_replicated'
        WHEN counts.n_direct > 0 THEN 'direct_evidence'
        WHEN counts.n_assoc_pubs >= 3 AND counts.n_assoc_directions <= 1
            THEN 'concordant_association'
        WHEN counts.n_model > 0 AND counts.n_assoc_pubs = 0 AND counts.n_weak = 0
            THEN 'computational_only'
        ELSE 'hypothesis_or_insufficient_support'
    END AS derived_reason
FROM assertion a
JOIN (
    SELECT
        a2.id AS assertion_id,
        (SELECT COUNT(*) FROM evidence_item e
          WHERE e.assertion_id = a2.id AND e.status = 'active') AS n_evidence,
        (SELECT COUNT(*) FROM evidence_item e
          WHERE e.assertion_id = a2.id AND e.status = 'active'
            AND e.evidence_type IN ('direct_perturbation', 'direct_biochemical')) AS n_direct,
        (SELECT COUNT(DISTINCT e.independent_group) FROM evidence_item e
          WHERE e.assertion_id = a2.id AND e.status = 'active'
            AND e.evidence_type IN ('direct_perturbation', 'direct_biochemical')
            AND e.independent_group IS NOT NULL) AS n_direct_groups,
        (SELECT COUNT(DISTINCT e.direction) FROM evidence_item e
          WHERE e.assertion_id = a2.id AND e.status = 'active'
            AND e.evidence_type IN ('direct_perturbation', 'direct_biochemical')
            AND e.direction IS NOT NULL) AS n_direct_directions,
        (SELECT COUNT(DISTINCT e.publication_id) FROM evidence_item e
          WHERE e.assertion_id = a2.id AND e.status = 'active'
            AND e.evidence_type IN ('correlative_omics', 'comparative_genomic')
            AND e.publication_id IS NOT NULL) AS n_assoc_pubs,
        (SELECT COUNT(DISTINCT e.direction) FROM evidence_item e
          WHERE e.assertion_id = a2.id AND e.status = 'active'
            AND e.evidence_type IN ('correlative_omics', 'comparative_genomic')
            AND e.direction IS NOT NULL) AS n_assoc_directions,
        (SELECT COUNT(*) FROM evidence_item e
          WHERE e.assertion_id = a2.id AND e.status = 'active'
            AND e.evidence_type = 'computational_model') AS n_model,
        (SELECT COUNT(*) FROM evidence_item e
          WHERE e.assertion_id = a2.id AND e.status = 'active'
            AND e.evidence_type IN ('literature_assertion', 'ai_inference')) AS n_weak,
        (SELECT COUNT(*) FROM conflict_member cm
           JOIN conflict c ON c.id = cm.conflict_id
          WHERE cm.assertion_id = a2.id AND c.kind = 'direction' AND c.status = 'open')
            AS n_open_direction_conflicts
    FROM assertion a2
) AS counts ON counts.assertion_id = a.id;


-- ---------------------------------------------------------------------------------------------
-- 13. Full text acquisition
--
-- src/fermdb/literature/acquire.py resolves open-access status and retrieves full text;
-- src/fermdb/literature/manual_queue.py handles what it could not. PLAN.md H.4 is binding: full
-- text is stored ONLY for content whose licence permits it -- everything else is a pointer
-- (a URL) plus, where a fetch was attempted, a record that it happened and why it did not yield
-- stored bytes.
--
-- Both tables are provenance of a retrieval attempt, not a scientific claim about the paper, so
-- they follow `raw_object`'s precedent above: zone 'R' by definition, no `evidence`/`confidence`
-- columns. `publication_id` is nullable on both because acquisition can run ahead of `publication`
-- being populated -- a DOI/PMID handed in from discovery may not have a `publication` row yet.
-- ---------------------------------------------------------------------------------------------

CREATE TABLE fulltext_asset (
    id                  TEXT PRIMARY KEY,
    publication_id      TEXT REFERENCES publication(id),
    doi                 TEXT,
    pmid                TEXT,
    oa_status           TEXT NOT NULL
                        CHECK (oa_status IN ('gold', 'green', 'hybrid', 'bronze', 'closed',
                                             'unknown')),
    license             TEXT,                -- as reported by the OA source; NULL = not stated
    -- Three states on purpose (CONVENTIONS.md "Missing values"): 'yes'/'no' is a resolved claim,
    -- 'unknown' is recorded-but-unresolved, and NULL is "no licence information reached us at
    -- all" -- distinct from having checked and found the licence ambiguous.
    text_mining_allowed TEXT CHECK (text_mining_allowed IN ('yes', 'no', 'unknown')),
    resolved_via        TEXT NOT NULL
                        CHECK (resolved_via IN ('unpaywall', 'europepmc', 'pmc', 'none')),
    -- Where bytes were found, whether or not they were stored: PLAN.md H.4 keeps a pointer even
    -- for a paper whose licence forbids storing a local copy.
    best_oa_url         TEXT,
    -- 'stored_fulltext' = the bytes below are ours; 'pointer_only' = oa_status/licence forbids
    -- storing a copy, only best_oa_url is kept; 'not_found' = nothing retrievable was resolved.
    storage_state       TEXT NOT NULL
                        CHECK (storage_state IN ('stored_fulltext', 'pointer_only', 'not_found')),
    content_path        TEXT,                -- relative to Settings.data_dir; NULL unless stored
    checksum_sha256     TEXT,
    media_type          TEXT,
    source_url          TEXT,                -- exact URL/origin the bytes came from, if any
    retrieved_at        TEXT,                -- ISO 8601 UTC; NULL if bytes were never fetched
    fetch_error         TEXT,                -- never silently dropped: why a fetch failed
    zone                TEXT NOT NULL DEFAULT 'R' CHECK (zone = 'R'),
    CHECK (doi IS NOT NULL OR pmid IS NOT NULL),
    -- The three "we actually kept bytes" columns agree with storage_state in both directions,
    -- the same discipline the three-state numerics elsewhere in this file use.
    CHECK (storage_state = 'stored_fulltext'
           OR (content_path IS NULL AND checksum_sha256 IS NULL)),
    CHECK (storage_state <> 'stored_fulltext'
           OR (content_path IS NOT NULL AND checksum_sha256 IS NOT NULL
               AND source_url IS NOT NULL AND retrieved_at IS NOT NULL))
);

CREATE INDEX fulltext_asset_by_doi ON fulltext_asset(doi);
CREATE INDEX fulltext_asset_by_pmid ON fulltext_asset(pmid);
-- A content hash is unique by construction; two rows sharing one would mean two publications
-- were byte-identical, which is worth refusing rather than silently allowing.
CREATE UNIQUE INDEX fulltext_asset_checksum_uq ON fulltext_asset(checksum_sha256)
    WHERE checksum_sha256 IS NOT NULL;

-- THE MANUAL DOWNLOAD QUEUE -- an explicit requirement from the project owner (PLAN.md H.4). A
-- paper that is not open access, or whose full text could not be retrieved, is recorded here
-- rather than dropped or retried forever: `manual_queue.py` exports the pending rows as a
-- worklist and re-ingests whatever the owner drops back into a folder. Same zone/no-evidence
-- rationale as `fulltext_asset` above -- this is acquisition logistics, not a biological claim.
CREATE TABLE manual_download_queue (
    id                     TEXT PRIMARY KEY,
    publication_id         TEXT REFERENCES publication(id),
    pmid                   TEXT,
    doi                    TEXT,
    title                  TEXT,
    journal                TEXT,
    year                   INTEGER,
    publisher_url          TEXT,
    best_known_link        TEXT,
    why_unavailable        TEXT NOT NULL
                           CHECK (why_unavailable IN ('paywalled', 'no_pdf_found',
                                                      'fetch_failed', 'licence_forbids')),
    -- Lower is more urgent. Always written by acquire.compute_priority from priority_topic and
    -- reports_titer_or_yield, never hand-set, so PLAN.md H.4's ranking rule
    -- (isobutanol > isobutanol x mitochondria > mtDNA engineering > ethanol, titer/yield papers
    -- first within a tier) lives in exactly one place and this column is only its recorded
    -- output.
    priority               INTEGER NOT NULL,
    priority_topic         TEXT NOT NULL
                           CHECK (priority_topic IN ('isobutanol', 'isobutanol_mitochondria',
                                                     'mtdna_engineering', 'ethanol', 'other')),
    -- Tri-state, deliberately nullable: NULL is "nobody has read the paper yet", 0 is
    -- "read, and it reports no titer or yield". NOT NULL DEFAULT 0 collapsed those into
    -- one, which CONVENTIONS.md "Missing values" forbids -- and it is load-bearing here,
    -- because priority ranks titer-reporting papers higher and "unknown" must not be
    -- silently ranked as "no". At enqueue time the paper has by definition not been read.
    reports_titer_or_yield INTEGER
                           CHECK (reports_titer_or_yield IS NULL
                                  OR reports_titer_or_yield IN (0, 1)),
    status                 TEXT NOT NULL DEFAULT 'pending'
                           CHECK (status IN ('pending', 'provided', 'skipped')),
    -- Set once `manual-queue ingest` matches a dropped-in file back to this row.
    fulltext_asset_id      TEXT REFERENCES fulltext_asset(id),
    notes                  TEXT,
    added_at               TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at             TEXT,
    zone                   TEXT NOT NULL DEFAULT 'R' CHECK (zone = 'R'),
    CHECK (doi IS NOT NULL OR pmid IS NOT NULL),
    CHECK (status = 'provided' OR fulltext_asset_id IS NULL)
);

-- One open row per paper: a repeated failed acquisition attempt updates the existing row (see
-- acquire.enqueue_manual_download) instead of piling up duplicates for the same DOI.
CREATE UNIQUE INDEX manual_download_queue_doi_uq ON manual_download_queue(doi)
    WHERE doi IS NOT NULL;
CREATE UNIQUE INDEX manual_download_queue_pmid_only_uq ON manual_download_queue(pmid)
    WHERE pmid IS NOT NULL AND doi IS NULL;
CREATE INDEX manual_download_queue_by_status_priority ON manual_download_queue(status, priority);


-- ---------------------------------------------------------------------------------------------
-- 14. Literature discovery
--
-- Corpus construction and inclusion triage (PLAN.md H.2, H.3, R.2), owned by
-- src/fermdb/literature/{eutils,discovery,queries}.py and driven by the versioned corpus
-- definition in data/literature/query_families.yaml. `publication` already exists in section 6
-- above and is reused as-is; nothing here modifies it.
--
-- search_run and screening_record are deliberately NOT zoned the way most fact tables are:
--
--   * search_run is a record of one E-utilities query having been executed -- a fact about a
--     computation, not a claim about biology -- and carries no `zone` at all, for exactly the
--     reason `processing_run` (section 7) already gives for the same choice.
--   * screening_record's `triage_state` is a deterministic function of query_families.yaml (repo
--     tier, Zone R) and the recorded rule in discovery.py: re-running the same family against the
--     same publication reproduces the same triage. That is Zone H's own definition
--     ("reconstructible from Zone R by running recorded code"), so it is stamped zone = 'H' and
--     that value is enforced by CHECK, exactly as `extraction` (section 6) enforces zone = 'I' for
--     the opposite reason. A future topical/relevance classifier (H.3) that scores title+abstract
--     is model output and MUST live in its own Zone I table with review_state = 'proposed' -- it
--     must never overwrite `triage_state` here directly.
-- ---------------------------------------------------------------------------------------------

CREATE TABLE search_run (
    id                      TEXT PRIMARY KEY,
    family                  TEXT NOT NULL,           -- query_families.yaml family name
    db                      TEXT NOT NULL,            -- 'pubmed' | 'pmc' | ...
    term                    TEXT NOT NULL,            -- the exact term(s) executed, for audit
    started_at              TEXT NOT NULL,
    finished_at             TEXT,
    -- esearch's reported count, summed across any criterion-tagged sub-queries; NOT deduplicated
    -- against other families or across sub-queries of the same family (that only happens once
    -- esummary/DOI data is in hand, at the screening_record level below).
    hit_count               INTEGER,
    retrieved_count         INTEGER,                 -- ids actually paged and passed to esummary
    query_families_version  INTEGER NOT NULL,        -- query_families.yaml `version` in effect
    dry_run                 INTEGER NOT NULL DEFAULT 0 CHECK (dry_run IN (0, 1))
);

CREATE INDEX search_run_by_family ON search_run(family, finished_at);

CREATE TABLE screening_record (
    id                   TEXT PRIMARY KEY,
    publication_id       TEXT NOT NULL REFERENCES publication(id),
    family               TEXT NOT NULL,
    first_seen_run_id    TEXT NOT NULL REFERENCES search_run(id),
    last_seen_run_id     TEXT NOT NULL REFERENCES search_run(id),
    triage_state         TEXT NOT NULL
                        CHECK (triage_state IN ('included', 'needs_full_text', 'excluded')),
    -- Never NULL for an exclusion: "an excluded paper is a decision, not an absence" (PLAN.md
    -- H.3), and a changed policy must be able to ask what it would now include, which requires
    -- knowing why each record was excluded in the first place. Citing this row's own family/term
    -- is not a substitute for a reason naming the actual policy applied.
    exclusion_reason     TEXT,
    -- The B.3 criterion (E1-E6, PLAN.md B.3) this hit is a full-text CANDIDATE for
    -- (triage_state = 'needs_full_text') or has been curator-confirmed under (triage_state =
    -- 'included'); NULL for 'excluded', and always NULL for an isobutanol-tier record, which has
    -- no admission criteria at all.
    admitted_criterion   TEXT CHECK (admitted_criterion IN ('E1', 'E2', 'E3', 'E4', 'E5', 'E6')),
    -- Denormalized from query_families.yaml as of the run that first wrote this row, so the R.2
    -- policy actually applied to THIS record stays legible even if the family's tier or default
    -- disposition changes later.
    product_tier         TEXT NOT NULL CHECK (product_tier IN ('isobutanol', 'ethanol')),
    default_disposition  TEXT NOT NULL
                        CHECK (default_disposition IN ('include_unless_excluded',
                                                       'exclude_unless_admitted')),
    pmid                 TEXT,
    doi                  TEXT,
    title_normalized     TEXT,
    -- Mirrors extraction.review_state (section 6): every automated triage starts 'proposed'. A
    -- curator moving a row to 'accepted' or 'rejected' is what stops a later discovery run from
    -- silently overwriting their judgement -- see the upsert logic in discovery.py, which only
    -- refreshes triage_state/exclusion_reason/admitted_criterion while review_state is still
    -- 'proposed', and otherwise only bumps last_seen_run_id.
    review_state         TEXT NOT NULL DEFAULT 'proposed'
                        CHECK (review_state IN ('proposed', 'accepted', 'rejected')),
    zone                 TEXT NOT NULL DEFAULT 'H' CHECK (zone = 'H'),
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (publication_id, family),
    CHECK (triage_state <> 'excluded' OR exclusion_reason IS NOT NULL),
    CHECK (admitted_criterion IS NULL OR product_tier = 'ethanol')
);

CREATE INDEX screening_record_by_triage ON screening_record(family, triage_state);
CREATE INDEX screening_record_by_publication ON screening_record(publication_id);


-- A curator's OWN include/exclude verdict, which `triage_state` above cannot hold.
--
-- The note at the head of this section says `triage_state` is "a deterministic function of
-- query_families.yaml and the recorded rule in discovery.py", which is why it is Zone H and why
-- anything else "must never overwrite `triage_state` here directly". A human who read the paper
-- and rejected it is not a function of the query file, so writing the verdict there would be
-- erased by the next discovery run and the papers would have to be read again.
--
-- Deleting the publication row is the other tempting answer and is worse. PLAN.md H.3: "an
-- excluded paper is a decision, not an absence." A dropped row cannot say why it went, and the
-- next discovery run re-adds it with no memory that anybody judged it -- which is precisely the
-- work this table exists to preserve.
--
-- One row per publication, keyed on it: the CURRENT verdict. Its history lives in
-- `curation_event`, as every other curator act's does.
CREATE TABLE screening_decision (
    publication_id  TEXT PRIMARY KEY REFERENCES publication(id),
    decision        TEXT NOT NULL CHECK (decision IN ('include', 'exclude', 'borderline')),
    -- Never NULL, for the same reason `screening_record.exclusion_reason` is never NULL on an
    -- exclusion: a changed policy must be able to ask what it would now include.
    reason          TEXT NOT NULL,
    -- Where the verdict was read from, so it can be re-derived rather than retyped: a folder the
    -- curator sorted PDFs into, a spreadsheet column, a session at the screen.
    source          TEXT NOT NULL,
    decided_by      TEXT NOT NULL,
    -- A person who read the paper and a classifier that scored its title are not the same grade
    -- of evidence, and must not be able to overwrite each other blind. Same argument
    -- curation_event.actor_kind makes with its CHECK that accept/promote require a human.
    decided_by_kind TEXT NOT NULL DEFAULT 'human'
                    CHECK (decided_by_kind IN ('human', 'model')),
    decided_at      TEXT NOT NULL,
    zone            TEXT NOT NULL DEFAULT 'R' CHECK (zone = 'R'),
    evidence        TEXT NOT NULL,
    confidence      TEXT NOT NULL
);

CREATE INDEX screening_decision_by_decision ON screening_decision(decision);
CREATE INDEX screening_decision_by_kind ON screening_decision(decided_by_kind);


-- ---------------------------------------------------------------------------------------------
-- 15. Extraction and curation
--
-- The curation queue, owned by src/fermdb/curate/queue.py, feeding on the `extraction` rows that
-- src/fermdb/extract/harness.py writes (section 6 above holds `extraction` and `span`; the
-- `actor_kind` column and the claim/release/accept/edit actions on `curation_event` in section 10
-- were added for this section).
--
-- The project owner's requirement is that curation runs as a SECONDARY, PARALLEL, BACKGROUND job
-- rather than as a step inside extraction, and three things in this table exist only because of
-- that:
--
--   * A LEASE, not a lock. `claimed_by` + `lease_expires_at` let several workers pull tasks at
--     once without collision, and let a task whose worker died be picked up again instead of
--     sitting 'in_progress' forever. Claiming is a compare-and-swap UPDATE (queue.claim_next), so
--     two workers that select the same row cannot both win.
--   * ONE TASK PER PROPOSED RECORD, not per extraction. A curator accepts or rejects one strain,
--     one measurement, one bottleneck. A whole-extraction verdict would force a reviewer to
--     reject eleven good rows to get rid of one bad one.
--   * REJECTIONS ARE RETAINED. A rejected task is never deleted -- `queue.py` contains no DELETE
--     at all, and a test asserts it stays that way. `proposal_hash` and `repeat_of` are why: a
--     model that keeps re-proposing something a curator already rejected is telling you something
--     about the model, and that signal exists only if the rejection is still there to match
--     against.
--
-- Zone I, like the extraction it came from: a proposed record supports no conclusion until a
-- curator promotes it, and promotion is a curator action only (PLAN.md L.1, L.5).
-- ---------------------------------------------------------------------------------------------

CREATE TABLE curation_task (
    id              TEXT PRIMARY KEY,
    extraction_id   TEXT NOT NULL REFERENCES extraction(id),
    publication_id  TEXT NOT NULL REFERENCES publication(id),
    -- 'measurements[0]' -- which record of which payload section this task is about. Unique per
    -- extraction, which is what makes enqueueing idempotent: a background scanner that runs twice
    -- over the same extraction creates the task once.
    record_path     TEXT NOT NULL,
    record_kind     TEXT NOT NULL,          -- strains | modifications | measurements | ...
    -- The single proposed record, as JSON, copied out of extraction.payload. Copied rather than
    -- joined so that a curator reviews exactly the bytes the task was created from even if the
    -- payload is later re-extracted under a new prompt version.
    payload         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'in_progress', 'accepted', 'edited', 'rejected')),
    -- Lower sorts first. A number rather than an enum so a policy can be tuned without a
    -- migration; the policy that sets it belongs in data, not here.
    priority        INTEGER NOT NULL DEFAULT 100,
    claimed_by      TEXT,                   -- worker id holding the lease
    claimed_at      TEXT,
    lease_expires_at TEXT,                  -- ISO 8601 UTC; past = reclaimable by another worker
    attempt_count   INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    curator         TEXT,
    curator_kind    TEXT CHECK (curator_kind IN ('human', 'agent')),
    resolved_at     TEXT,
    resolution_reason TEXT,
    -- Set only by an 'edited' resolution: the curator's corrected record. The original stays in
    -- `payload`, because what the model proposed and what a human had to fix are two facts.
    edited_payload  TEXT,
    -- sha256 over (publication_id, record_kind, the record with span offsets removed). Two
    -- proposals of the same claim hash the same even if the model re-derived the offsets.
    proposal_hash   TEXT NOT NULL,
    -- The earlier task, if any, that proposed the same thing and was rejected.
    repeat_of       TEXT REFERENCES curation_task(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    zone            TEXT NOT NULL DEFAULT 'I' CHECK (zone = 'I'),
    -- A claimed task names its holder and when the claim lapses, or it is not really claimed.
    CHECK (status <> 'in_progress'
           OR (claimed_by IS NOT NULL AND claimed_at IS NOT NULL
               AND lease_expires_at IS NOT NULL)),
    -- A resolved task names who resolved it, when and why. Same reasoning as `extraction`'s
    -- review columns: a verdict with no name attached is not a curation record.
    CHECK (status IN ('pending', 'in_progress')
           OR (curator IS NOT NULL AND curator_kind IS NOT NULL AND resolved_at IS NOT NULL
               AND resolution_reason IS NOT NULL)),
    -- PLAN.md L.5, at the storage layer: only a human resolves. An agent worker can hold a lease
    -- and hand it back; it cannot decide.
    CHECK (status IN ('pending', 'in_progress') OR curator_kind = 'human'),
    CHECK (status <> 'edited' OR edited_payload IS NOT NULL),
    CHECK (status = 'edited' OR edited_payload IS NULL)
);

-- One task per proposed record. The uniqueness is the idempotency guarantee, not a nicety.
CREATE UNIQUE INDEX curation_task_record_uq ON curation_task(extraction_id, record_path);
-- The pull query: the next unclaimed (or lease-expired) task, highest priority first.
CREATE INDEX curation_task_pull ON curation_task(status, priority, created_at);
-- The re-proposal lookup: has a curator already rejected this exact claim?
CREATE INDEX curation_task_by_proposal ON curation_task(proposal_hash, status);
CREATE INDEX curation_task_by_extraction ON curation_task(extraction_id);


-- ---------------------------------------------------------------------------------------------
-- 16. Omics acquisition
--
-- Metadata harvested from SRA and GEO (docs/reference/DATA_VOLUME.md section 2, PLAN.md F),
-- owned by src/fermdb/omics/{sra,geo,references}.py and driven by the curated query definitions
-- in data/omics/dataset_families.yaml. This is a METADATA-ONLY layer: `sra_run.location_url`
-- records where a run's bytes live, but nothing in this section means they have been fetched.
-- `raw_object` (section 7 above) is the only table that means "we actually have these bytes", and
-- it stays empty until the separate, explicitly costed bulk-download step of
-- docs/reference/DATA_VOLUME.md section 6 is run -- src/fermdb/omics/sra.py has no function that
-- performs it (`download_run_bytes` is a deliberate tripwire, not a stub).
--
-- `dataset` (section 7) is extended here rather than duplicated: a GEO series' esummary response
-- and an SRA study both fit its existing shape and just needed a few more columns. `sample_count`
-- is the count SRA/GEO themselves reported, not a derived COUNT(*) over `sra_run` -- the two can
-- differ (a series can list samples with no public run yet), and collapsing them would hide that.
-- ---------------------------------------------------------------------------------------------

ALTER TABLE dataset ADD COLUMN bioproject TEXT;   -- PRJNA...; how a GEO series links to SRA runs
ALTER TABLE dataset ADD COLUMN title TEXT;
ALTER TABLE dataset ADD COLUMN organism TEXT;
ALTER TABLE dataset ADD COLUMN sample_count INTEGER
    CHECK (sample_count IS NULL OR sample_count >= 0);
ALTER TABLE dataset ADD COLUMN retrieved_at TEXT;

-- One row per SRA run, the finest grain SRA reports at. `dataset_id` resolves to the GEO series
-- sharing this run's bioproject when one exists, else to an SRA-study-level `dataset` row, else
-- NULL -- an unresolved link is not an absent run (src/fermdb/omics/sra.py:resolve_dataset_id).
--
-- Fixed Zone R: every column is exactly what SRA's runinfo reported, not a curator's or model's
-- reading of it -- `library_strategy` in particular is submitter-supplied and occasionally wrong,
-- but recording the mislabel is Zone R's job, not this table's.
CREATE TABLE sra_run (
    id                   TEXT PRIMARY KEY,       -- insdc.sra:SRR...
    run_accession        TEXT NOT NULL UNIQUE,    -- SRR...
    dataset_id           TEXT REFERENCES dataset(id),
    experiment_accession TEXT,                    -- SRX...
    study_accession      TEXT,                    -- SRP...
    bioproject           TEXT,                    -- PRJNA...
    biosample            TEXT,                    -- SAMN...
    organism             TEXT,
    taxid                INTEGER,
    library_strategy     TEXT,                    -- RNA-Seq | WGS | AMPLICON | Tn-Seq | OTHER | ...
    library_layout       TEXT CHECK (library_layout IN ('SINGLE', 'PAIRED', 'unknown')),
    platform             TEXT,
    instrument_model     TEXT,
    spots                INTEGER CHECK (spots IS NULL OR spots >= 0),
    bases                INTEGER CHECK (bases IS NULL OR bases >= 0),
    size_mb              REAL CHECK (size_mb IS NULL OR size_mb >= 0),
    -- Where the bytes can be fetched from, exactly as SRA's runinfo reported it (an NCBI, AWS or
    -- GCP URL depending on the run). A location, not a retrieval: nothing has moved.
    location_url         TEXT,
    -- PLAN.md F.3: a run enters quantification only once its conditions are annotated, which this
    -- metadata-only harvest never does, so 'discovered' is the only state this package writes.
    acquisition_status   TEXT NOT NULL DEFAULT 'discovered'
                         CHECK (acquisition_status IN ('discovered', 'condition_annotated',
                                                       'queued', 'excluded')),
    -- DATA_VOLUME.md section 2: Tn-Seq runs are perturbation evidence (L1/L2 under J.3), not
    -- correlation (L3), so per run they are the most informative rows in the corpus. Lower sorts
    -- first; src/fermdb/omics/sra.py:priority_rank_for is the one place this rule is computed.
    priority_rank        INTEGER NOT NULL DEFAULT 100,
    retrieved_at         TEXT NOT NULL,
    zone                 TEXT NOT NULL DEFAULT 'R' CHECK (zone = 'R'),
    evidence             TEXT NOT NULL,
    confidence           TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);

CREATE INDEX sra_run_by_dataset ON sra_run(dataset_id);
CREATE INDEX sra_run_by_priority ON sra_run(priority_rank, run_accession);

-- Added for "see transcriptomic data is based on which genome, analyse according to that"
-- (SCHEMA_VERSION -> 4, entry 4b; a concurrent, unrelated bump in the same round briefly pushed
-- this to 5 and was reconciled back on review -- see src/fermdb/db/__init__.py's version-history
-- comment). The isobutanol SRA corpus spans five organisms
-- (docs/reference/DATA_VOLUME.md section 2), so the reference is chosen PER RUN by
-- src/fermdb/omics/references.py:select_reference, off data/omics/reference_genomes.yaml --
-- never a single atlas-wide reference.
--
-- reference_assembly is deliberately a free-text accession, not a foreign key into
-- reference_sequence: that table only ever holds the S288C anchor's own fetched bytes (nuclear +
-- mitochondrial), never the CEN.PK/Ethanol Red/bacterial assemblies this atlas catalogs but has
-- not fetched byte-for-byte (see reference_genome_asset below for the ones it has).
ALTER TABLE sra_run ADD COLUMN reference_assembly TEXT;
-- The literal 'none' is a real, stored value ("a catalog was consulted and nothing matched"), not
-- interchangeable with the column being NULL ("selection was never attempted") -- the same
-- NULL-vs-sentinel distinction CONVENTIONS.md draws for NULL vs 'NA' vs 'unknown' elsewhere.
ALTER TABLE sra_run ADD COLUMN reference_match_quality TEXT
    CHECK (reference_match_quality IS NULL
           OR reference_match_quality IN ('strain_matched', 'species_exact', 'species_proxy',
                                           'none'));
-- PLAN.md F.4: the reference-choice loss must be MEASURED, not assumed. NULL until a
-- quantification pipeline (not yet built in this codebase) populates it; src/fermdb/omics/sra.py
-- never writes a value here, and its UPSERT deliberately never touches this column on conflict
-- either, so a later quantification write survives a re-run of discovery.
ALTER TABLE sra_run ADD COLUMN unmapped_fraction REAL
    CHECK (unmapped_fraction IS NULL OR (unmapped_fraction BETWEEN 0 AND 1));
-- Set for a run whose match to a curated query term may be a false positive (e.g. this corpus's 8
-- Fusarium graminearum runs against the term "isobutanol") rather than a genuine corpus member --
-- src/fermdb/omics/references.py:is_relevance_uncertain. Curator review, not deletion (PLAN.md
-- S.3 "never guess"); always computed (defaults to 0), unlike the two reference_* columns above.
ALTER TABLE sra_run ADD COLUMN relevance_uncertain INTEGER NOT NULL DEFAULT 0
    CHECK (relevance_uncertain IN (0, 1));

-- The small DNA references this pass fetches in full (DATA_VOLUME.md sections 0 and 5): the
-- S288C nuclear assembly and the mitochondrial genome, content-addressed by sha256 so the exact
-- bytes behind any downstream analysis are always re-derivable (PLAN.md N.2, J.5 provenance).
CREATE TABLE reference_sequence (
    id                   TEXT PRIMARY KEY,
    kind                 TEXT NOT NULL CHECK (kind IN ('nuclear_genome', 'nuclear_annotation',
                                                       'mitochondrial_genome',
                                                       'mitochondrial_annotation')),
    organism_id          TEXT REFERENCES organism(id),
    assembly_accession   TEXT NOT NULL,           -- e.g. GCF_000146045.2
    sequence_accession   TEXT NOT NULL,           -- e.g. NC_001224.1
    -- The genome that carries this sequence, and hence (via encoding_genome) the NCBI
    -- translation table it must be read by.
    encoding_genome      TEXT NOT NULL REFERENCES encoding_genome(id),
    file_path            TEXT NOT NULL,           -- content-addressed path under Settings.genomes_dir
    checksum_sha256      TEXT NOT NULL,
    size_bytes           INTEGER NOT NULL CHECK (size_bytes >= 0),
    source_url           TEXT NOT NULL,
    -- Set once src/fermdb/omics/references.py:verify_mitochondrial_translation has translated this
    -- sequence's annotated CDS under encoding_genome's table and matched NCBI's own /translation
    -- -- the check that proves the fetched reference and genetic_code.py agree, per this task.
    translation_verified INTEGER NOT NULL DEFAULT 0 CHECK (translation_verified IN (0, 1)),
    retrieved_at         TEXT NOT NULL,
    zone                 TEXT NOT NULL DEFAULT 'R' CHECK (zone = 'R'),
    evidence             TEXT NOT NULL,
    confidence           TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high')),
    UNIQUE (sequence_accession, kind)
);

CREATE INDEX reference_sequence_by_assembly ON reference_sequence(assembly_accession);

-- Fetched-and-checksummed bytes for a reference genome OTHER than the S288C anchor (item 5: "the
-- bacterial genomes, they are small, 2-5 Mb" -- also open to CEN.PK/Ethanol Red if either is ever
-- fetched in full). Deliberately separate from `reference_sequence` above: this table carries no
-- genetic-code claim at all (no `kind` CHECK restricted to nuclear/mitochondrial, no
-- `encoding_genome` foreign key), because a bacterial replicon reads under NCBI genetic code table
-- 11, which `encoding_genome` does not model (that table is yeast-specific: nuclear/mitochondrial,
-- tables 1/3 -- src/fermdb/genetic_code.py). `reference_id` is a free-text slug into
-- data/omics/reference_genomes.yaml, not a foreign key: that file is curated data, not a table.
CREATE TABLE reference_genome_asset (
    id                 TEXT PRIMARY KEY,
    reference_id       TEXT NOT NULL,           -- e.g. 'ecoli_k12_mg1655' (data/omics/reference_genomes.yaml)
    organism           TEXT NOT NULL,
    sequence_accession TEXT NOT NULL,           -- e.g. NC_000913.3
    kind               TEXT NOT NULL CHECK (kind IN ('genome', 'annotation')),
    file_path          TEXT NOT NULL,           -- content-addressed path under Settings.genomes_dir
    checksum_sha256    TEXT NOT NULL,
    size_bytes         INTEGER NOT NULL CHECK (size_bytes >= 0),
    source_url         TEXT NOT NULL,
    retrieved_at       TEXT NOT NULL,
    zone               TEXT NOT NULL DEFAULT 'R' CHECK (zone = 'R'),
    evidence           TEXT NOT NULL,
    confidence         TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high')),
    UNIQUE (sequence_accession, kind)
);

CREATE INDEX reference_genome_asset_by_reference ON reference_genome_asset(reference_id);


-- ---------------------------------------------------------------------------------------------
-- 17. Functional annotation
--
-- Owned by src/fermdb/annotate/ (sources.py, importers.py). THE KEY DESIGN POINT, restated from
-- that package's docstring: for every organism in DUET_TARGET.md/ISOBUTANOL_PROGRAM.md's roster
-- -- S. cerevisiae and, per the owner's directive, the bacterial hosts studied for comparison
-- (E. coli, Z. mobilis, L. cremoris, C. glutamicum, B. subtilis) -- GO terms, pathway/KO/EC
-- membership, protein domains, cofactor specificity, subcellular location, transporter family,
-- complex membership, TF targets and phenotypes are ALREADY CURATED at SGD/UniProt/KEGG/
-- Pfam/InterPro/TCDB/Complex Portal, better than this atlas could compute it from sequence alone.
-- `gene_annotation` below is therefore an IMPORT target, not a computation target: one row per
-- (gene_group, source, term), each carrying the source's own identifier, label and (for GO) its
-- evidence code -- never a locally re-derived score.
--
-- Two things are the opposite of that and stay OUT of this table on purpose, because no source
-- above provides either systematically and both sit on DUET's own critical path
-- (docs/design/DUET_TARGET.md section 2, "Mitochondrial, not cytosolic" and "Fe-S protection,
-- dual-purpose"): mitochondrial targeting-sequence/presequence prediction (yeast only), and Fe-S
-- cluster protein annotation (Ilv3 is the named critical case). `fermdb.annotate` carries their
-- interfaces as TODO stubs (`PresequencePrediction`/`FeSClusterAnnotation`); neither is
-- implemented, and no row in this table can have come from such a computation -- `zone` stays
-- 'R' for every row an importer writes (exactly what the source reported), never 'I'.
--
-- `gene_annotation.source` names one row of data/annotation/annotation_sources.yaml, which is the
-- licence/redistributability authority (KEGG, TCDB and YEASTRACT+ are marked
-- redistributable: false there -- their importers store identifiers and links only, never a
-- copied-out reaction list, pathway map, or bulk export); this schema does not repeat that policy
-- in a CHECK, because "what may be redistributed" is a fact about the source, not a shape the
-- database can enforce on a row already written.
--
-- `evidence_code` is GO's own vocabulary (IDA, IEA, ...), carried through unflattened per
-- docs/reference/CONVENTIONS.md "Evidence" rather than collapsed into one confidence value --
-- `fermdb.annotate.sources.go_evidence_category`/`recommended_confidence_for_go_evidence` is the
-- mapping this atlas uses onto its own confidence vocabulary (IDA-class codes are direct
-- experimental evidence and rate higher than IEA-class electronic/computational ones). The CHECK
-- below makes it structurally impossible for a non-GO source to carry one, the same way
-- `evidence_item`'s per-evidence-type CHECKs (section 10) make it impossible for a row to lie
-- about what kind of evidence it is.
--
-- `reaction_id`/`pathway_id` are the "pathway/reaction linkage" this section adds without
-- duplicating either table: set ONLY when a term already resolves to a row this atlas
-- independently curates (an EC/KO already given its own `reaction`, or a KEGG pathway map already
-- given its own `pathway`, both in ISOBUTANOL_PROGRAM.md's hand-modelled route) -- NULL for the
-- overwhelming majority of rows, which point at the external source only.
-- ---------------------------------------------------------------------------------------------

CREATE TABLE gene_annotation (
    id             TEXT PRIMARY KEY,          -- YAA:ANNOT:<uuid>
    gene_group_id  TEXT NOT NULL REFERENCES gene_group(id),
    source         TEXT NOT NULL CHECK (source IN ('sgd_go', 'uniprot_goa', 'kegg', 'pfam',
                                                   'interpro', 'uniprot', 'tcdb', 'complex_portal',
                                                   'yeastract', 'sgd_phenotype')),
    term_id        TEXT NOT NULL,             -- GO:0006094 | K00826 | PF00106 | IPR002198 | ...
    term_label     TEXT,
    term_namespace TEXT,                      -- GO aspect, or 'pathway'/'ko'/'ec'/'domain'/...
    -- GO evidence codes ONLY (IDA, IEA, ...); NULL for every non-GO source, because the concept
    -- does not exist there -- a structurally absent field on that row's source, not an
    -- unresolved fact (docs/reference/CONVENTIONS.md "Missing values" governs a fact a source
    -- could have recorded but didn't, not a column a row's own source-type never had).
    evidence_code  TEXT,
    reaction_id    TEXT REFERENCES reaction(id),
    pathway_id     TEXT REFERENCES pathway(id),
    source_url     TEXT,                      -- resolved from annotation_sources.yaml's url_pattern
    source_version TEXT,                      -- release/version string the source reported, if any
    retrieved_at   TEXT,
    zone           TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence       TEXT NOT NULL,
    confidence     TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high')),
    CHECK (evidence_code IS NULL OR source IN ('sgd_go', 'uniprot_goa'))
);

CREATE INDEX gene_annotation_by_gene_group ON gene_annotation(gene_group_id, source);
CREATE INDEX gene_annotation_by_term ON gene_annotation(source, term_id);

-- The idempotency key src/fermdb/annotate/importers.py re-imports against
-- (find_gene_annotation/write_gene_annotation): COALESCE folds NULL evidence_code to '' because
-- SQLite's plain UNIQUE treats every NULL as distinct from every other NULL, which would let two
-- non-GO rows for the same (gene_group, source, term) both insert instead of the second updating
-- the first.
CREATE UNIQUE INDEX gene_annotation_dedup
    ON gene_annotation(gene_group_id, source, term_id, COALESCE(evidence_code, ''));
