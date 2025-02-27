import sys
import subprocess
import os
import shutil
import argparse
import json
import re
from enum import Enum
from dataclasses import dataclass
import gbench
from gbench import util, report
from gbench.util import *

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

class ScoreResult(Enum):
    SKIPPED = READY = 0
    BUILD_FAILED = 1
    BENCH_FAILED = 2
    PASSED = 3

@dataclass
class LabParams:
    threshold: float = 10.0
    result: ScoreResult = ScoreResult.SKIPPED

@dataclass
class LabPath:
    category: str
    name: str

parser = argparse.ArgumentParser(description='test results')
parser.add_argument("-workdir", type=str, help="working directory", default="")
parser.add_argument("-v", help="verbose", action="store_true", default=False)

args = parser.parse_args()
workdir = args.workdir
verbose = args.v

Labs = dict()
Labs["memory_bound"] = dict()
Labs["core_bound"] = dict()
Labs["bad_speculation"] = dict()
Labs["frontend_bound"] = dict()
Labs["data_driven"] = dict()
Labs["misc"] = dict()

Labs["memory_bound"]["data_packing"] = LabParams(threshold=15.0)
Labs["memory_bound"]["loop_interchange_1"] = LabParams(threshold=85.0)
Labs["memory_bound"]["loop_interchange_2"] = LabParams(threshold=75.0)
Labs["misc"]["warmup"] = LabParams(threshold=50.0)
Labs["core_bound"]["function_inlining_1"] = LabParams(threshold=35.0)
Labs["core_bound"]["compiler_intrinsics_1"] = LabParams(threshold=60.0)
Labs["core_bound"]["vectorization_1"] = LabParams(threshold=90.0)

def getLabCurrentStatus(labPath):
  return Labs[labPath.category][labPath.name].result

def setLabCurrentStatus(labPath, status):
  Labs[labPath.category][labPath.name].result = status
  return True

def getLabThreshold(labPath):
  return Labs[labPath.category][labPath.name].threshold

def getLabNameStr(labPath):
  return labPath.category + ":" + labPath.name

def buildAndValidate(labBuildDir):
  try:
    subprocess.check_call("cmake -E make_directory " + labBuildDir, shell=True)
    print("Prepare build directory - OK")
  except:
    print(bcolors.FAIL + "Prepare build directory - Failed" + bcolors.ENDC)
    return False

  os.chdir(labBuildDir)

  try:
    subprocess.check_call("cmake -DCMAKE_BUILD_TYPE=Release -DCI=ON " + os.path.join(labBuildDir, ".."), shell=True)
    print("CMake - OK")
  except:
    print(bcolors.FAIL + "CMake - Failed" + bcolors.ENDC)
    return False

  try:
    subprocess.check_call("cmake --build . --config Release --target clean", shell=True)
    subprocess.check_call("cmake --build . --config Release --parallel 8", shell=True)
    print("Build - OK")
  except:
    print(bcolors.FAIL + "Build - Failed" + bcolors.ENDC)
    return False

  try:
    subprocess.check_call("cmake --build . --config Release --target validateLab", shell=True)
    print("Validation - OK")
  except:
    print(bcolors.FAIL + "Validation - Failed" + bcolors.ENDC)
    return False

  return True

def buildLab(labDir, solutionOrBaseline):
  os.chdir(labDir)
  buildDir = os.path.join(labDir, "build_" + solutionOrBaseline)
  print("Build and Validate the " + solutionOrBaseline)
  if not buildAndValidate(buildDir):
    return False

  return True

def noChangesToTheBaseline(labDir):
  solutionDir = os.path.join(labDir, "build_solution")
  baselineDir = os.path.join(labDir, "build_baseline")
  solutionExe = os.path.join(solutionDir, "lab" if sys.platform != 'win32' else os.path.join("Release", "lab.exe"))
  baselineExe = os.path.join(baselineDir, "lab" if sys.platform != 'win32' else os.path.join("Release", "lab.exe"))
  exit_code = subprocess.call(("cmp " if sys.platform != 'win32' else "fc /b >NUL ") + solutionExe + " " + baselineExe, shell=True)
  return exit_code == 0

def checkoutBaseline(workdir):
  os.chdir(workdir)

  try:
    # Branch 'main' is always the baseline
    subprocess.check_call("git checkout main", shell=True)
    print("Checkout baseline - OK")
  except:
    print(bcolors.FAIL + "Checkout baseline - Failed" + bcolors.ENDC)
    return False

  return True

def getSpeedUp(diff_report):
  old = diff_report[0]['measurements'][0]['real_time']
  new = diff_report[0]['measurements'][0]['real_time_other']
  diff = old - new
  speedup = (diff / old ) * 100
  return speedup

def benchmarkSolutionOrBaseline(labBuildDir, solutionOrBaseline):
  #os.chdir(labBuildDir)
  try:
    subprocess.check_call("cmake --build " + labBuildDir + " --config Release --target benchmarkLab", shell=True)
    print("Benchmarking " + solutionOrBaseline + " - OK")
  except:
    print(bcolors.FAIL + "Benchmarking " + solutionOrBaseline + " - Failed" + bcolors.ENDC)
    return False

  return True

def benchmarkLab(labPath):

  print("Benchmark solution against the baseline")

  labDir = os.path.join(workdir, labPath.category, labPath.name)

  solutionDir = os.path.join(labDir, "build_solution")
  baselineDir = os.path.join(labDir, "build_baseline")

  benchmarkSolutionOrBaseline(solutionDir, "solution")
  benchmarkSolutionOrBaseline(baselineDir, "baseline")

  outJsonSolution = gbench.util.load_benchmark_results(os.path.join(solutionDir, "result.json"))
  outJsonBaseline = gbench.util.load_benchmark_results(os.path.join(baselineDir, "result.json"))

  # Parse two report files and compare them
  diff_report = gbench.report.get_difference_report(
    outJsonBaseline, outJsonSolution, True)
  output_lines = gbench.report.print_difference_report(
    diff_report,
    False, True, 0.05, True)
  for ln in output_lines:
    print(ln)

  speedup = getSpeedUp(diff_report)
  if abs(speedup) < 2.0:
    print (bcolors.FAIL + "New version has performance similar to the baseline (<2% difference). Submission for the lab " + getLabNameStr(labPath) + " failed." + bcolors.ENDC)
    return False
  if speedup < 0:
    print (bcolors.FAIL + "New version is slower. Submission for the lab " + getLabNameStr(labPath) + " failed." + bcolors.ENDC)
    return False

  if (speedup < getLabThreshold(labPath)):
    print (bcolors.FAIL + "Submission for the lab " + getLabNameStr(labPath) + " failed. New version is not fast enough." + bcolors.ENDC)
    print ("Measured speedup:", "{:.2f}".format(speedup), "%")
    print ("Pass threshold:", "{:.2f}".format(getLabThreshold(labPath)), "%")
    return False

  print ("Measured speedup:", "{:.2f}".format(speedup), "%")
  print (bcolors.OKGREEN + "Submission succeded" + bcolors.ENDC)
  return True

def runActionForAllLabs(workdir, func):
  for labCategory in os.listdir(workdir):
    if labCategory in Labs:
      categoryDir = os.path.join(workdir, labCategory)
      for labName in os.listdir(categoryDir):
        if labName in Labs[labCategory]:
          labPath = LabPath(labCategory, labName)
          if (getLabCurrentStatus(labPath) == ScoreResult.READY):
            func(labPath)

def buildSolutionAction(labPath):
  labWorkDir = os.path.join(workdir, labPath.category, labPath.name)
  if not buildLab(labWorkDir, "solution"):
    setLabCurrentStatus(labPath, ScoreResult.BUILD_FAILED)

def buildBaselineAction(labPath):
  labWorkDir = os.path.join(workdir, labPath.category, labPath.name)
  if not buildLab(labWorkDir, "baseline"):
    setLabCurrentStatus(labPath, ScoreResult.BUILD_FAILED)

def benchmarkAction(labPath):
  labWorkDir = os.path.join(workdir, labPath.category, labPath.name)
  if noChangesToTheBaseline(labWorkDir):
    setLabCurrentStatus(labPath, ScoreResult.SKIPPED)
  elif not benchmarkLab(labPath):
    setLabCurrentStatus(labPath, ScoreResult.BENCH_FAILED)
  else:
    setLabCurrentStatus(labPath, ScoreResult.PASSED)

def checkAllLabs(workdir):
  runActionForAllLabs(workdir, buildSolutionAction)
  if not checkoutBaseline(workdir):
    return False
  runActionForAllLabs(workdir, buildBaselineAction)
  runActionForAllLabs(workdir, benchmarkAction)

  return True

def changedMultipleLabs(lines):
  percent1, path1 = lines[1].split(b'%')
  GitShowLabPath1 = DirLabPathRegex.search(str(path1))
  if (GitShowLabPath1):
    for i in range(2, len(lines)):
      if len(lines[i]) == 0:
        continue
      percent_i, path_i = lines[i].split(b'%')
      GitShowLabPath_i = DirLabPathRegex.search(str(path_i))
      if (GitShowLabPath_i):
        if GitShowLabPath1.group(1) != GitShowLabPath_i.group(1) or GitShowLabPath1.group(2) != GitShowLabPath_i.group(2):
          return True
  return False

if not workdir:
  print ("Error: working directory is not provided.")
  sys.exit(1)

os.chdir(workdir)

checkAll = False
benchLabPath = 0
DirLabPathRegex = re.compile(r'labs/(.*)/(.*)/')

try:
  outputGitLog = subprocess.check_output("git log -1 --oneline" , shell=True)
  # If the commit message has '[CheckAll]' substring, benchmark everything
  if b'[CheckAll]' in outputGitLog:
    checkAll = True
    print("Will benchmark all the labs")
  # Otherwise, analyze the changes made in the last commit and identify which lab to benchmark
  else:
    outputGitShow = subprocess.check_output("git show -1 --dirstat --oneline" , shell=True)
    lines = outputGitShow.split(b'\n')
    # Expect at least 2 lines in the output
    if (len(lines) < 2 or len(lines[1]) == 0):
      print("Can't figure out which lab was changed in the last commit. Will benchmark all the labs.")
      checkAll = True
    elif changedMultipleLabs(lines):
      print("Multiple labs changed. Will benchmark all the labs.")
      checkAll = True
    else:
      # Skip the first line that has the commit hash and message
      percent, path = lines[1].split(b'%')
      GitShowLabPath = DirLabPathRegex.search(str(path))
      if (GitShowLabPath):
        benchLabPath = LabPath(GitShowLabPath.group(1), GitShowLabPath.group(2))
        print("Will benchmark the lab: " + getLabNameStr(benchLabPath))
      else:
        print("Can't figure out which lab was changed in the last commit. Will benchmark all the labs.")
        checkAll = True
except:
  print("Error: can't fetch the last commit from git history")
  sys.exit(1)

result = False
if checkAll:
  if not checkAllLabs(workdir):
    sys.exit(1)
  print(bcolors.HEADER + "\nLab Assignments Summary:" + bcolors.ENDC)
  allSkipped = True
  for category in Labs:
    print(bcolors.HEADER + "  " + category + ":" + bcolors.ENDC)
    for lab in Labs[category]:
      if ScoreResult.SKIPPED == Labs[category][lab].result:
        print(bcolors.OKCYAN + "    " + lab + ": Skipped" + bcolors.ENDC)
      else:
        allSkipped = False
      if ScoreResult.PASSED == Labs[category][lab].result:
        print(bcolors.OKGREEN + "    " + lab + ": Passed" + bcolors.ENDC)
        # Return true if at least one lab succeeded
        result = True
      if ScoreResult.BENCH_FAILED == Labs[category][lab].result:
        print(bcolors.FAIL + "    " + lab + ": Failed: not fast enough" + bcolors.ENDC)
      if ScoreResult.BUILD_FAILED == Labs[category][lab].result:
        print(bcolors.FAIL + "    " + lab + ": Failed: build error" + bcolors.ENDC)
  if allSkipped:
    result = True
else:
  labdir = os.path.join(workdir, benchLabPath.category, benchLabPath.name)
  if not buildLab(labdir, "solution"):
    sys.exit(1)
  if not checkoutBaseline(workdir):
    sys.exit(1)
  if not buildLab(labdir, "baseline"):
    sys.exit(1)
  if noChangesToTheBaseline(labdir):
    print(bcolors.OKCYAN + "The solution and the baseline are identical. Skipped." + bcolors.ENDC)
    result = True
  else:
    result = benchmarkLab(benchLabPath)

if not result:
  sys.exit(1)
else:
  sys.exit(0)
