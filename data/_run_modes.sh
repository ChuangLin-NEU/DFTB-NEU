#!/bin/bash
d=/home/neu123/.dftb-neu/jobs/edu_ad35a4b452
export PATH="$HOME/.dftb-neu/envs/dftbplus/bin:$PATH"
cd "$d" || exit 1
cat > modes_in.hsd <<'EOF'
Geometry = GenFormat {
  <<< "geo.gen"
}
DisplayModes = {
  PlotModes = 1:15
  Animate = Yes
}
SlaterKosterFiles = Type2FileNames {
  Prefix = "/home/neu123/.dftb-neu/share/dftb/sk/3ob/"
  Separator = "-"
  Suffix = ".skf"
}
Hessian = {
  <<< "hessian.out"
}
InputVersion = 3
EOF
modes > modes2.log 2>&1
echo EXIT:$?
ls -la *.xyz vibrations* modes_out* 2>/dev/null
echo '==== LOG TAIL ===='
tail -80 modes2.log
