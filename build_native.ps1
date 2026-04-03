$ErrorActionPreference = "Stop"

$include = "C:\Users\Ya\AppData\Local\Programs\Python\Python313\Include"
$libs = "C:\Users\Ya\AppData\Local\Programs\Python\Python313\libs"
$output = "doomgame\doom_native_renderer.cp313-win_amd64.pyd"
$vcvars = "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat"

cmd /c "call ""$vcvars"" && cl /nologo /O2 /std:c++14 /EHsc /LD /I""$include"" native\doom_native_renderer.cpp /link /LIBPATH:""$libs"" python313.lib /OUT:""$output"""

if (-not (Test-Path $output)) {
  throw "Build failed: $output not found"
}

Write-Host "Built $output"
