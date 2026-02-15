#!/usr/bin/env python3
"""
@doc
Quick Architecture Check Script

A lightweight script to quickly validate backend architecture and detect
circular dependencies or layer violations. Designed for CI/CD integration.

Examples:
    python> # Quick check (exit code 0 = clean, 1 = issues found)
    python> python scripts/check_architecture.py
    
    python> # Verbose output
    python> python scripts/check_architecture.py --verbose
"""

import sys
import subprocess
from pathlib import Path


def run_analysis() -> tuple[bool, dict]:
    """Run the circular dependency analysis and return results.
    
    This function executes a subprocess to run the script
    "analyze_circular_dependencies.py" located in the parent  directory of the
    current file. It captures the output and  parses it to extract the number of
    circular dependencies  and architectural violations. The function returns a
    tuple  indicating whether the analysis is clean and a dictionary  containing
    the extracted metrics and the subprocess output.
    """
    try:
        result = subprocess.run([
            sys.executable, 
            str(Path(__file__).parent / "analyze_circular_dependencies.py")
        ], capture_output=True, text=True, cwd=Path(__file__).parent.parent)
        
        # Parse the output to extract key metrics
        output_lines = result.stdout.split('\n')
        circular_deps = 0
        violations = 0
        
        for line in output_lines:
            if "Circular Dependencies:" in line:
                circular_deps = int(line.split(':')[1].strip())
            elif "Architectural Violations:" in line:
                violations = int(line.split(':')[1].strip())
        
        clean = circular_deps == 0 and violations == 0
        return clean, {
            'circular_dependencies': circular_deps,
            'architectural_violations': violations,
            'exit_code': result.returncode,
            'output': result.stdout
        }
    except Exception as e:
        return False, {'error': str(e)}


def main():
    """Run the main analysis of the backend architecture.
    
    This function checks the backend architecture by running an analysis  and
    reporting on any circular dependencies or architectural violations  found. It
    utilizes the `run_analysis` function to perform the analysis  and processes the
    results to provide feedback to the user. The output  varies based on whether
    issues are detected and can be verbose if  specified in the command line
    arguments.
    """
    verbose = '--verbose' in sys.argv or '-v' in sys.argv
    
    print("🔍 Checking backend architecture...")
    
    clean, results = run_analysis()
    
    if 'error' in results:
        print(f"❌ Analysis failed: {results['error']}")
        return 1
    
    # Summary
    circular = results['circular_dependencies']
    violations = results['architectural_violations']
    
    if clean:
        print("✅ Architecture check passed!")
        print(f"   • Circular dependencies: {circular}")
        print(f"   • Layer violations: {violations}")
    else:
        print("⚠️  Architecture issues detected:")
        if circular > 0:
            print(f"   • {circular} circular dependencies found")
        if violations > 0:
            print(f"   • {violations} architectural layer violations found")
        
        print("\n🔧 Run full analysis for details:")
        print("   python scripts/analyze_circular_dependencies.py")
    
    if verbose:
        print("\n" + "="*60)
        print("FULL OUTPUT:")
        print("="*60)
        print(results['output'])
    
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())