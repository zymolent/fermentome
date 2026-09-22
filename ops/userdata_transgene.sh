#!/bin/bash
# fermdb requantification of SRP342112 against the TRANSGENE-AUGMENTED transcriptome.
#
# The 33 runs of SRP342112 are an isobutanol producer series in a CEN.PK113-5D background whose
# strains carry HETEROLOGOUS genes: Lactococcus lactis adhA (as the 29C8 point-mutant) and
# Escherichia coli ilvC (as the 6E6 point-mutant), alongside the yeast ILV2/ILV3/ILV5/ARO10.
# Every earlier quantification used an S288C-only index, so reads from the two BACTERIAL genes had
# nowhere to map and sit in the unmapped fraction. The atlas therefore could not say whether the
# KARI and ADH steps of these builds are transcribed at all -- which is the question being asked.
#
# This run uses s288c.transcripts.transgene.fna.gz: the same mitochondria-complete transcriptome
# plus five heterologous CDS, each under a [locus_tag=TRANSGENE_*] that transcript_to_gene resolves
# to an unmistakable gene id. Wild-type CDS are used on purpose: reads from a few-residue variant
# still map to the wild-type sequence, and the variants' own sequences are not public.
#
# Yeast only. The E. coli and L. cremoris quantifications are unaffected and are not repeated.
#
# Self-terminating by three independent mechanisms, because the expensive failure here is an
# instance nobody notices:
#   1. instance-initiated-shutdown-behavior=terminate (set at launch)
#   2. trap on EXIT -> shutdown, so every exit path terminates
#   3. a detached watchdog that shuts down at 4h no matter what the main script is doing
exec > >(tee -a /var/log/fermdb.log) 2>&1
B=fermdb-raw-211125789985
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
P=quant-transgene/$STAMP

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
aws s3 cp "s3://$B/refs/s288c.transcripts.transgene.fna.gz" . --only-show-errors
aws s3 cp "s3://$B/refs/s288c.genome.fna.gz" . --only-show-errors
aws s3 cp "s3://$B/refs/quant_plan_transgene.json" /scratch/ --only-show-errors

# Sanity check before spending an hour on an index. A silently-truncated upload would index
# cleanly, quantify cleanly, and reproduce the exact gap this run exists to close -- so the five
# transgene CDS and the 19 mitochondrial CDS are both counted, and a shortfall aborts.
TG=$(zcat s288c.transcripts.transgene.fna.gz | grep -c 'locus_tag=TRANSGENE_' || echo 0)
MT=$(zcat s288c.transcripts.transgene.fna.gz | grep -c 'NC_001224.1_cds_' || echo 0)
echo "transgene CDS present: $TG ; mtDNA CDS present: $MT"
zcat s288c.transcripts.transgene.fna.gz | grep 'locus_tag=TRANSGENE_' | cut -c1-120
if [ "$TG" -lt 5 ] || [ "$MT" -lt 19 ]; then
  echo "=== ABORT: expected 5 transgene and 19 mtDNA CDS, found $TG and $MT ==="
  exit 10
fi

# Decoy-aware gentrome, as before: genomic sequence as decoy suppresses spurious mappings of
# pre-mRNA and genomic carryover. The transgenes are absent from the yeast genome and so are not
# decoyed by it, which is correct -- there is no yeast locus they could be confused with.
zcat s288c.genome.fna.gz | grep '^>' | cut -d' ' -f1 | sed 's/>//' > decoys.txt
cat s288c.transcripts.transgene.fna.gz s288c.genome.fna.gz > s288c.gentrome.fna.gz
salmon index -t s288c.gentrome.fna.gz -d decoys.txt -i /scratch/idx_s288c -k 31 -p 16 2>&1 | tail -5
ls -la /scratch/

echo "=== QUANT $(date -u) ==="
mkdir -p /scratch/work /scratch/out
jq -r '.[] | [.run, .ref, .layout] | @tsv' /scratch/quant_plan_transgene.json > /scratch/runs.tsv
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
# How much of this run landed on the heterologous CDS: the number the whole exercise is for.
TGREADS=$(awk 'NR>1 && $1 ~ /_TRANSGENE[0-9]+$/ {s+=$5} END{printf "%.0f", s+0}' quant/quant.sf)
ADHA=$(awk 'NR>1 && $1 ~ /AAK05905.1_TRANSGENE/ {printf "%.0f", $5}' quant/quant.sf)
ILVC=$(awk 'NR>1 && $1 ~ /NP_418222.1_TRANSGENE/ {printf "%.0f", $5}' quant/quant.sf)
log "mapped=${MR}% reads=${NP} transgene_reads=${TGREADS} adhA=${ADHA} ilvC=${ILVC}"
aws s3 cp quant/quant.sf "s3://$B/$P/quant/$ACC/quant.sf" --only-show-errors
aws s3 cp quant/aux_info/meta_info.json "s3://$B/$P/quant/$ACC/meta_info.json" --only-show-errors
aws s3 cp quant/lib_format_counts.json "s3://$B/$P/quant/$ACC/lib_format_counts.json" --only-show-errors 2>/dev/null
cd /scratch && rm -rf "$D"
EOS
chmod +x /scratch/one.sh

# 3 concurrent runs x 5 threads = 15 of 16 vCPU (the account's on-demand vCPU limit is 16, so a
# larger instance cannot be launched even though 33 runs would happily use one).
awk '{print $1"\t"$2"\t"$3}' /scratch/runs.tsv | \
  xargs -P 3 -n 3 bash -c '/scratch/one.sh "$0" "$1" "$2" '"$B $P"'' || true

echo "=== SUMMARY $(date -u) ==="
DONE=$(aws s3 ls "s3://$B/$P/quant/" --recursive | grep -c 'quant.sf' || echo 0)
TOTAL=$(wc -l < /scratch/runs.tsv)
echo "quantified $DONE of $TOTAL"
grep -o 'transgene_reads=[0-9]*' /var/log/fermdb.log | sort -t= -k2 -n | tail -5
printf '{"stamp":"%s","done":%s,"total":%s,"transcriptome":"s288c.transcripts.transgene.fna.gz","study":"SRP342112"}\n' \
  "$STAMP" "$DONE" "$TOTAL" > /scratch/summary.json
aws s3 cp /scratch/summary.json "s3://$B/$P/summary.json" --only-show-errors
echo "=== DONE $(date -u) ==="
