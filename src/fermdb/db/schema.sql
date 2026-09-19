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

CREATE TABLE product (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
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

CREATE TABLE metabolite (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    inchikey   TEXT,
    chebi_id   TEXT,
    formula    TEXT,
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
    zone           TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    evidence       TEXT NOT NULL,
    confidence     TEXT NOT NULL CHECK (confidence IN ('unverified', 'low', 'medium', 'high'))
);

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
CREATE TABLE extraction (
    id                TEXT PRIMARY KEY,
    publication_id    TEXT NOT NULL REFERENCES publication(id),
    extractor         TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    prompt_version    TEXT,
    review_state      TEXT NOT NULL DEFAULT 'pending'
                      CHECK (review_state IN ('pending', 'accepted', 'rejected')),
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    zone              TEXT NOT NULL DEFAULT 'I' CHECK (zone = 'I')
);

-- The exact text an extraction came from. 0-based half-open [char_start, char_end).
CREATE TABLE span (
    id             TEXT PRIMARY KEY,
    publication_id TEXT NOT NULL REFERENCES publication(id),
    extraction_id  TEXT REFERENCES extraction(id),
    section        TEXT,
    char_start     INTEGER,
    char_end       INTEGER,
    quoted_text    TEXT,
    zone           TEXT NOT NULL CHECK (zone IN ('R', 'H', 'I')),
    CHECK (char_start IS NULL OR char_end IS NULL OR char_end > char_start)
);


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

CREATE TABLE curation_event (
    id          TEXT PRIMARY KEY,
    curator     TEXT NOT NULL,
    action      TEXT NOT NULL CHECK (action IN ('create', 'promote', 'reject', 'supersede',
                                                'override_level', 'resolve_conflict', 'comment')),
    target_type TEXT NOT NULL,
    target_id   TEXT NOT NULL,              -- polymorphic; see header note
    -- A rejection is recorded, not deleted: a rejected extraction that keeps being re-proposed
    -- is a signal about the model, and throwing it away loses that signal.
    rationale   TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    zone        TEXT NOT NULL DEFAULT 'R' CHECK (zone = 'R')
);


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
