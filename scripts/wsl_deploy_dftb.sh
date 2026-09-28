#!/usr/bin/env bash
# DFTB Neu：在 Linux / WSL 用户目录隔离部署 DFTB+（不用 sudo）
set -euo pipefail
CMATS_ROOT="${DFTB_NEU_HOME:-$HOME/.dftb-neu}"
BIN_DIR="$CMATS_ROOT/bin"
ENV_DIR="$CMATS_ROOT/envs/dftbplus"
SK_ROOT="$CMATS_ROOT/share/dftb/sk"
JOB_ROOT="$CMATS_ROOT/jobs"
mkdir -p "$BIN_DIR" "$CMATS_ROOT/envs" "$CMATS_ROOT/tmp" "$SK_ROOT" "$JOB_ROOT"

echo "DEPLOY_ROOT=$CMATS_ROOT"

MM="$BIN_DIR/micromamba"
CONDA_MIRRORS=(
  "https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge"
  "https://mirrors.ustc.edu.cn/anaconda/cloud/conda-forge"
)
fetch_url() {
  local dest="$1"
  shift
  local url
  rm -f "$dest"
  for url in "$@"; do
    echo "FETCH=$url"
    if command -v curl >/dev/null 2>&1; then
      curl -fL --retry 2 --connect-timeout 15 --max-time 180 -o "$dest" "$url" && [ -s "$dest" ] && return 0
    else
      wget -T 30 -O "$dest" "$url" && [ -s "$dest" ] && return 0
    fi
    rm -f "$dest"
  done
  return 1
}

if [ ! -x "$MM" ]; then
  ARCH=$(uname -m)
  case "$ARCH" in
    x86_64|amd64) MM_ARCH=linux-64 ;;
    aarch64|arm64) MM_ARCH=linux-aarch64 ;;
    *) echo "UNSUPPORTED_ARCH=$ARCH"; exit 2 ;;
  esac
  TMP="$CMATS_ROOT/tmp/micromamba.tar.bz2"
  MM_OK=0
  for ver in "2.9.0-0" "2.8.4-0" "2.3.3-0"; do
    fetch_url "$TMP" \
      "https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge/${MM_ARCH}/micromamba-${ver}.tar.bz2" \
      "https://mirrors.ustc.edu.cn/anaconda/cloud/conda-forge/${MM_ARCH}/micromamba-${ver}.tar.bz2" \
      && MM_OK=1 && break
  done
  if [ "$MM_OK" != "1" ]; then
    echo "MICROMAMBA_DOWNLOAD_FAIL"
    exit 3
  fi
  mkdir -p "$CMATS_ROOT/tmp/mmextract"
  if tar -xjf "$TMP" -C "$CMATS_ROOT/tmp/mmextract" bin/micromamba 2>/dev/null; then
    :
  elif command -v python3 >/dev/null 2>&1; then
    python3 - "$TMP" "$CMATS_ROOT/tmp/mmextract" <<'PY'
import sys, tarfile
src, dest = sys.argv[1], sys.argv[2]
with tarfile.open(src, "r:bz2") as tf:
    members = [m for m in tf.getmembers() if m.name.endswith("bin/micromamba") or m.name == "bin/micromamba"]
    if not members:
        members = [m for m in tf.getmembers() if m.name.endswith("micromamba")]
    tf.extractall(dest, members=members or None)
PY
  else
    echo "NEED_BZIP2_OR_PYTHON3"
    exit 3
  fi
  if [ -f "$CMATS_ROOT/tmp/mmextract/bin/micromamba" ]; then
    mv "$CMATS_ROOT/tmp/mmextract/bin/micromamba" "$MM"
  else
    found=$(find "$CMATS_ROOT/tmp/mmextract" -type f -name micromamba | head -n 1 || true)
    if [ -n "$found" ]; then
      mv "$found" "$MM"
    else
      echo "MICROMAMBA_EXTRACT_FAIL"
      exit 3
    fi
  fi
  chmod +x "$MM"
  echo "MICROMAMBA_INSTALLED"
fi

GLIBC_MAJ=$(ldd --version 2>&1 | head -n1 | grep -oE '[0-9]+\.[0-9]+' | head -n1 || echo 2.17)
GLIBC_OK_FLAG=1
case "$GLIBC_MAJ" in
  2.1[7-9]|2.2[0-7]|2.[0-9]|1.*) GLIBC_OK_FLAG=0 ;;
esac
echo "GLIBC=$GLIBC_MAJ modern=$GLIBC_OK_FLAG"

if [ -x "$ENV_DIR/bin/dftb+" ] && "$ENV_DIR/bin/dftb+" --version >/dev/null 2>&1; then
  echo "ENV_OK"
else
  if [ -e "$ENV_DIR" ]; then
    mv "$ENV_DIR" "${ENV_DIR}_broken_$$" 2>/dev/null || rm -rf "$ENV_DIR"
  fi
  created=0
  for ch in "${CONDA_MIRRORS[@]}"; do
    echo "CONDA_CHANNEL=$ch"
    if [ "$GLIBC_OK_FLAG" = "1" ]; then
      "$MM" create -y -p "$ENV_DIR" --override-channels -c "$ch" 'dftbplus=*=nompi_*' dftbplus-tools && created=1 && break
      "$MM" create -y -p "$ENV_DIR" --override-channels -c "$ch" dftbplus dftbplus-tools && created=1 && break
    else
      "$MM" create -y -p "$ENV_DIR" --override-channels -c "$ch" 'dftbplus=21.2' && created=1 && break
      "$MM" create -y -p "$ENV_DIR" --override-channels -c "$ch" 'dftbplus=22.2' && created=1 && break
    fi
  done
  if [ "$created" != "1" ]; then
    echo "ENV_CREATE_FAIL"
    exit 4
  fi
  echo "ENV_CREATED"
fi

download_sk() {
  local set="$1"
  local dest="$SK_ROOT/$set"
  if find "$dest" -name '*.skf' 2>/dev/null | grep -q .; then
    echo "SK_EXISTS=$set"
    return 0
  fi
  mkdir -p "$dest"
  local tar="$CMATS_ROOT/tmp/${set}.tar.gz"
  fetch_url "$tar" \
    "https://ghfast.top/https://github.com/dftbparams/${set}/archive/refs/heads/main.tar.gz" \
    "https://gitclone.com/github.com/dftbparams/${set}/archive/refs/heads/main.tar.gz" \
    || return 1
  mkdir -p "$CMATS_ROOT/tmp/sk_$set"
  tar -xzf "$tar" -C "$CMATS_ROOT/tmp/sk_$set"
  find "$CMATS_ROOT/tmp/sk_$set" -name '*.skf' -exec cp -f {} "$dest/" \;
  n=$(find "$dest" -name '*.skf' | wc -l | tr -d ' ')
  echo "SK_OK=$set count=$n"
}

for s in 3ob mio matsci pbc; do
  download_sk "$s" || echo "SK_FAIL=$s"
done

export PATH="$ENV_DIR/bin:$PATH"
echo "FEATURE_PROBE_BEGIN"
dftb+ --version 2>&1 | head -n 8 || true
which dftb+
echo "SK_TOTAL=$(find "$SK_ROOT" -name '*.skf' | wc -l | tr -d ' ')"
echo "FEATURE_PROBE_END"

# H2O 测试校验（Recipes）
SMOKE="$JOB_ROOT/smoke_h2o"
rm -rf "$SMOKE"
mkdir -p "$SMOKE"
cat > "$SMOKE/geo.gen" <<'GEN'
3 C
 O H
    1    1    0.00000000000E+00  -1.00000000000E+00   0.00000000000E+00
    2    2    0.00000000000E+00   0.00000000000E+00   0.78306400000E+00
    3    2    0.00000000000E+00   0.00000000000E+00  -0.78306400000E+00
GEN
SK3OB="$SK_ROOT/3ob"
cat > "$SMOKE/dftb_in.hsd" <<HSD
Geometry = GenFormat {
  <<< "geo.gen"
}
Hamiltonian = DFTB {
  SCC = Yes
  ThirdOrderFull = Yes
  HubbardDerivs {
    O = -0.1575
    H = -0.1857
  }
  MaxAngularMomentum {
    O = "p"
    H = "s"
  }
  SlaterKosterFiles = Type2FileNames {
    Prefix = "${SK3OB}/"
    Separator = "-"
    Suffix = ".skf"
  }
  Filling = Fermi {
    Temperature [K] = 300
  }
}
Driver = GeometryOptimization {
  Optimizer = Rational {}
  MaxSteps = 50
  OutputPrefix = "geo_end"
  Convergence = {
    GradElem = 1E-4
  }
}
Options {
  WriteDetailedOut = Yes
}
InputVersion = "24.1"
HSD
(cd "$SMOKE" && dftb+ > dftb.log 2>&1) || true
if grep -q "Geometry converged" "$SMOKE/detailed.out" 2>/dev/null; then
  echo "SMOKE_OK"
else
  echo "SMOKE_FAIL"
  tail -40 "$SMOKE/dftb.log" || true
fi
echo "DEPLOY_OK"
