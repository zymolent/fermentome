#!/bin/bash
# fermdb requantification of SRP342112 against the CASSETTE-augmented transcriptome.
#
# This supersedes ops/userdata_transgene.sh for this study. That first pass added the WILD-TYPE
# bacterial CDS (L. lactis adhA, E. coli ilvC/ilvD, L. lactis kivd) on the assumption that reads
# from a few-residue variant still map to the wild type. That assumption is wrong here: the study
# is Gambacorta et al. 2022 (Synth Syst Biotechnol 7(2):738-749, GEO GSE186126) and its cassette
# is deposited as GenBank MZ541859.1, in which EVERY ORF is codon-optimized. Synthetic ORFs do not
# map to their wild-type parents, and -- more seriously -- they do not map cleanly to their NATIVE
# S288C counterparts either, so the cassette copies of ILV2/ILV3/ILV5/ARO10 have until now been
# scored partly against the native rows.
#
# The index here therefore carries the seven MZ541859.1 ORFs under [locus_tag=cassette_*], beside
# the untouched native loci, so that cassette and native expression are separate rows that can be
# compared rather than one row that silently mixes them.
#
# Two deliberate departures, both recorded rather than assumed:
#  * The wild-type adhA/kivd/ilvD are NOT in this index. They would compete with the cassette ORFs
#    for the same reads, and kivd/ilvD are not in any of these strains anyway.
#  * The wild-type E. coli ilvC IS kept. MZ541859.1 is the mIBA-Ilv5 plasmid (the Y797 build) and
#    contains no ilvC; no plasmid for the Y799 build is deposited. Dropping ilvC would make "is the
#    KARI step of Y799 transcribed" unanswerable by construction. It has no cassette counterpart
#    here, so it competes with nothing.
#
# Reads are PAIRED 2x151 as submitted, whatever the paper's methods section says; the script
# detects layout from the dump rather than trusting either.
#
# Self-terminating by three independent mechanisms, because the expensive failure here is an
# instance nobody notices:
#   1. instance-initiated-shutdown-behavior=terminate (set at launch)
#   2. trap on EXIT -> shutdown, so every exit path terminates
#   3. a detached watchdog that shuts down at 4h no matter what the main script is doing
exec > >(tee -a /var/log/fermdb.log) 2>&1
B=fermdb-raw-211125789985
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
P=quant-cassette/$STAMP

finish() {
  echo "=== FINISH $(date -u) ==="
  aws s3 cp /var/log/fermdb.log "s3://$B/$P/run.log" --only-show-errors || true
  shutdown -h now
}
trap finish EXIT
( sleep 14400; echo "=== HARD TIMEOUT 4h ==="; \
  aws s3 cp /var/log/fermdb.log "s3://$B/$P/run.log.timeout" --only-show-errors || true; \
  shutdown -h now ) &

set -x
echo "=== SETUP $(date -u) ==="
dnf install -y -q tar bzip2 jq >/dev/null
mkfs -t xfs /dev/nvme1n1 2>/dev/null || true
mkdir -p /scratch && mount /dev/nvme1n1 /scratch 2>/dev/null || mkdir -p /scratch
cd /opt
curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xj bin/micromamba
export MAMBA_ROOT_PREFIX=/opt/mamba
/opt/bin/micromamba create -y -q -p /opt/env -c conda-forge -c bioconda salmon sra-tools pigz
export PATH=/opt/env/bin:$PATH
salmon --version; fasterq-dump --version

echo "=== REFERENCES $(date -u) ==="
mkdir -p /scratch/refs && cd /scratch/refs
aws s3 cp "s3://$B/refs/s288c.transcripts.cassette.fna.gz" . --only-show-errors
aws s3 cp "s3://$B/refs/s288c.genome.fna.gz" . --only-show-errors
aws s3 cp "s3://$B/refs/quant_plan_cassette.json" /scratch/ --only-show-errors

# Sanity check before spending money on an index. A silently-truncated upload would index cleanly,
# quantify cleanly, and reproduce the exact gap this run exists to close. The native loci are
# checked too, because an index with the cassette but without native ILV3 would make the
# native-versus-cassette comparison -- the whole point of this pass -- quietly meaningless.
CAS=$(zcat s288c.transcripts.cassette.fna.gz | grep -c 'locus_tag=cassette_' || echo 0)
ILVC=$(zcat s288c.transcripts.cassette.fna.gz | grep -c 'locus_tag=wildtype_EcIlvC' || echo 0)
MT=$(zcat s288c.transcripts.cassette.fna.gz | grep -c 'NC_001224.1_cds_' || echo 0)
NAT=$(zcat s288c.transcripts.cassette.fna.gz | grep -cE 'locus_tag=(YMR108W|YJR016C|YLR355C|YDR380W)' || echo 0)
echo "cassette ORFs: $CAS ; wildtype ilvC: $ILVC ; mtDNA CDS: $MT ; native ILV2/3/5/ARO10: $NAT"
zcat s288c.transcripts.cassette.fna.gz | grep -E 'locus_tag=(cassette_|wildtype_)' | cut -c1-130
if [ "$CAS" -lt 7 ] || [ "$ILVC" -lt 1 ] || [ "$MT" -lt 19 ] || [ "$NAT" -lt 4 ]; then
  echo "=== ABORT: expected 7 cassette, 1 ilvC, 19 mtDNA, 4 native; found $CAS $ILVC $MT $NAT ==="
  exit 10
fi

# Decoy-aware gentrome, as before. The cassette integrates at HO and its ORFs are synthetic, so
# they are absent from the S288C genome and are not decoyed by it -- which is correct: there is no
# genomic locus they could be confused with, and that is precisely what separates them from the
# native rows.
zcat s288c.genome.fna.gz | grep '^>' | cut -d' ' -f1 | sed 's/>//' > decoys.txt
cat s288c.transcripts.cassette.fna.gz s288c.genome.fna.gz > s288c.gentrome.fna.gz
salmon index -t s288c.gentrome.fna.gz -d decoys.txt -i /scratch/idx_s288c -k 31 -p 16 2>&1 | tail -5
ls -la /scratch/

echo "=== QUANT $(date -u) ==="
mkdir -p /scratch/work /scratch/out
jq -r '.[] | [.run, .ref, .layout] | @tsv' /scratch/quant_plan_cassette.json > /scratch/runs.tsv
wc -l /scratch/runs.tsv

cat > /scratch/one.sh <<'EOS'
#!/bin/bash
set -o pipefail
ACC=$1; REF=$2; LAYOUT=$3; B=$4; P=$5
D=/scratch/work/$ACC
mkdir -p "$D" && cd "$D" || exit 1
log(){ echo "[$ACC] $*"; }
if aws s3 ls "s3://$B/$P/quant/$ACC/quant.sf" >/dev/null 2>&1; then log "already done"; exit 0; fi
aws s3 cp "s3://$B/raw/sra/$ACC/$ACC" "./$ACC.sra" --only-show-errors || { log "DOWNLOAD FAILED"; exit 2; }
fasterq-dump --split-3 -e 5 -O . "./$ACC.sra" >/dev/null 2>&1 || { log "DUMP FAILED"; exit 3; }
rm -f "./$ACC.sra"
IDX=/scratch/idx_$REF
if [ -s "${ACC}_1.fastq" ] && [ -s "${ACC}_2.fastq" ]; then
  salmon quant -i "$IDX" -l A -1 "${ACC}_1.fastq" -2 "${ACC}_2.fastq" \
    -p 5 --validateMappings --seqBias --gcBias -o quant >/dev/null 2>&1 || { log "QUANT FAILED"; exit 4; }
elif [ -s "${ACC}.fastq" ]; then
  salmon quant -i "$IDX" -l A -r "${ACC}.fastq" \
    -p 5 --validateMappings --seqBias -o quant >/dev/null 2>&1 || { log "QUANT FAILED"; exit 4; }
else
  log "NO FASTQ PRODUCED"; exit 5
fi
MR=$(jq -r '.percent_mapped' quant/aux_info/meta_info.json 2>/dev/null)
NP=$(jq -r '.num_processed' quant/aux_info/meta_info.json 2>/dev/null)
CASR=$(awk 'NR>1 && $1 ~ /_CASSETTE[0-9]+$/ {s+=$5} END{printf "%.0f", s+0}' quant/quant.sf)
ADHA=$(awk 'NR>1 && $1 ~ /UUV68060.1_CASSETTE/ {printf "%.0f", $5}' quant/quant.sf)
KANR=$(awk 'NR>1 && $1 ~ /UUV68063.1_CASSETTE/ {printf "%.0f", $5}' quant/quant.sf)
ILVC=$(awk 'NR>1 && $1 ~ /_WTILVC$/ {printf "%.0f", $5}' quant/quant.sf)
log "mapped=${MR}% reads=${NP} cassette_reads=${CASR} adhA=${ADHA} kanR=${KANR} ilvC=${ILVC}"
aws s3 cp quant/quant.sf "s3://$B/$P/quant/$ACC/quant.sf" --only-show-errors
aws s3 cp quant/aux_info/meta_info.json "s3://$B/$P/quant/$ACC/meta_info.json" --only-show-errors
aws s3 cp quant/lib_format_counts.json "s3://$B/$P/quant/$ACC/lib_format_counts.json" --only-show-errors 2>/dev/null
cd /scratch && rm -rf "$D"
EOS
chmod +x /scratch/one.sh

# 3 concurrent runs x 5 threads = 15 of 16 vCPU (the account's on-demand vCPU limit is 16).
awk '{print $1"\t"$2"\t"$3}' /scratch/runs.tsv | \
  xargs -P 3 -n 3 bash -c '/scratch/one.sh "$0" "$1" "$2" '"$B $P"'' || true

echo "=== SUMMARY $(date -u) ==="
DONE=$(aws s3 ls "s3://$B/$P/quant/" --recursive | grep -c 'quant.sf' || echo 0)
TOTAL=$(wc -l < /scratch/runs.tsv)
echo "quantified $DONE of $TOTAL"
grep -o 'cassette_reads=[0-9]*' /var/log/fermdb.log | sort -t= -k2 -n | tail -5
printf '{"stamp":"%s","done":%s,"total":%s,"transcriptome":"s288c.transcripts.cassette.fna.gz","study":"SRP342112","cassette":"MZ541859.1"}\n' \
  "$STAMP" "$DONE" "$TOTAL" > /scratch/summary.json
aws s3 cp /scratch/summary.json "s3://$B/$P/summary.json" --only-show-errors
echo "=== DONE $(date -u) ==="
