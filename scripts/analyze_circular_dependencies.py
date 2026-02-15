#!/usr/bin/env python3
"""
@doc
Circular Dependency Analyzer for Backend Architecture

This script analyzes the backend Python codebase to detect circular imports,
architectural violations, and dependency relationships. It provides detailed
reports on the module import graph and identifies problematic patterns.

Examples:
    python> # Run complete analysis
    python> analyzer = CircularDependencyAnalyzer('/home/yan/A101/HR/backend')
    python> analyzer.analyze()
    python> analyzer.generate_report()
"""

import ast
import os
import sys
from pathlib import Path
from typing import Dict, Set, List, Tuple, Optional, Any
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
import json


@dataclass
class ImportInfo:
    """Information about an import statement."""
    module: str
    from_module: Optional[str]
    alias: Optional[str]
    line_number: int
    is_relative: bool
    level: int = 0  # Relative import level (0 for absolute imports)


@dataclass
class CircularDependency:
    """Information about a detected circular dependency."""
    cycle: List[str]
    strength: int  # Number of imports in the cycle
    
    
@dataclass
class ArchitecturalViolation:
    """Information about architectural layer violations."""
    violator: str
    target: str
    violation_type: str
    description: str


class ImportVisitor(ast.NodeVisitor):
    """AST visitor to extract import information from Python files."""
    
    def __init__(self, module_path: str):
        self.module_path = module_path
        self.imports: List[ImportInfo] = []
        
    def visit_Import(self, node: ast.Import):
        """Visit regular import statements and collect import information."""
        for alias in node.names:
            self.imports.append(ImportInfo(
                module=alias.name,
                from_module=None,
                alias=alias.asname,
                line_number=node.lineno,
                is_relative=False,
                level=0
            ))
        self.generic_visit(node)
        
    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Visit from-import statements."""
        if node.module:
            for alias in node.names:
                self.imports.append(ImportInfo(
                    module=node.module,
                    from_module=alias.name,
                    alias=alias.asname,
                    line_number=node.lineno,
                    is_relative=node.level > 0,
                    level=node.level
                ))
        self.generic_visit(node)


class CircularDependencyAnalyzer:
    """Main analyzer for detecting circular dependencies and architectural violations."""
    
    def __init__(self, backend_path: str):
        self.backend_path = Path(backend_path)
        self.module_imports: Dict[str, List[ImportInfo]] = {}
        self.dependency_graph: Dict[str, Set[str]] = defaultdict(set)
        self.circular_dependencies: List[CircularDependency] = []
        self.architectural_violations: List[ArchitecturalViolation] = []
        
        # Define architectural layers
        self.layers = {
            'api': {'level': 4, 'can_import': ['services', 'core', 'models', 'utils']},
            'services': {'level': 3, 'can_import': ['core', 'models', 'utils']},
            'core': {'level': 2, 'can_import': ['models', 'utils']},
            'models': {'level': 1, 'can_import': ['utils']},
            'utils': {'level': 0, 'can_import': []},
            'tools': {'level': -1, 'can_import': ['services', 'core', 'models', 'utils']}  # Special case
        }
    
    def normalize_module_path(self, file_path: Path) -> str:
        """Convert file path to module notation."""
        try:
            relative_path = file_path.relative_to(self.backend_path.parent)
            parts = list(relative_path.parts)
            
            # Remove .py extension
            if parts[-1].endswith('.py'):
                parts[-1] = parts[-1][:-3]
                
            # Remove __init__
            if parts[-1] == '__init__':
                parts = parts[:-1]
                
            return '.'.join(parts)
        except ValueError:
            return str(file_path)
    
    def resolve_import_module(self, import_info: ImportInfo, current_module: str) -> Optional[str]:
        """Resolve import to actual module path.
        
        This function determines the actual module path based on the provided  import
        information and the current module context. It handles both  relative and
        absolute imports, adjusting the module path according to  the specified import
        level. For relative imports, it constructs the  target module path by
        manipulating the current module's parts, while  for absolute imports, it checks
        if the module starts with 'backend.'  or is a backend-relative import.
        
        Args:
            import_info (ImportInfo): Information about the import, including
                whether it is relative and the module name.
            current_module (str): The name of the current module from which
                the import is being resolved.
        """
        if import_info.is_relative:
            # Handle relative imports
            current_parts = current_module.split('.')
            if import_info.module:
                # from .module import something
                if import_info.level == 1:
                    # Single dot - same directory
                    target_parts = current_parts[:-1] + [import_info.module]
                elif import_info.level == 2:
                    # Double dot - parent directory  
                    target_parts = current_parts[:-2] + [import_info.module]
                else:
                    # Multiple dots - go up multiple levels
                    target_parts = current_parts[:-(import_info.level-1)] + [import_info.module]
            else:
                # from . import something - import from same package
                target_parts = current_parts[:-1]
            return '.'.join(target_parts)
        else:
            # Absolute import - only track internal modules
            if import_info.module.startswith('backend.'):
                return import_info.module
            # Also check for backend-relative imports (common pattern)
            elif any(part == 'backend' for part in current_module.split('.')):
                # This might be a backend-relative import
                current_parts = current_module.split('.')
                backend_index = current_parts.index('backend')
                potential_module = '.'.join(current_parts[:backend_index+1] + [import_info.module])
                return potential_module
            return None
    
    def extract_imports(self, file_path: Path) -> List[ImportInfo]:
        """Extract import information from a Python file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content)
            visitor = ImportVisitor(str(file_path))
            visitor.visit(tree)
            return visitor.imports
        except Exception as e:
            print(f"Warning: Could not parse {file_path}: {e}")
            return []
    
    def analyze_file(self, file_path: Path):
        """Analyze a single Python file for its imports and build a dependency graph."""
        module_name = self.normalize_module_path(file_path)
        imports = self.extract_imports(file_path)
        
        self.module_imports[module_name] = imports
        
        # Build dependency graph
        for import_info in imports:
            resolved_module = self.resolve_import_module(import_info, module_name)
            if resolved_module and resolved_module != module_name:
                self.dependency_graph[module_name].add(resolved_module)
    
    def find_cycles(self) -> List[List[str]]:
        """Find all cycles in the dependency graph using DFS."""
        visited = set()
        rec_stack = set()
        cycles = []
        
        def dfs(node: str, path: List[str]) -> bool:
            """Performs a depth-first search to detect cycles in a graph."""
            if node in rec_stack:
                # Found a cycle
                cycle_start = path.index(node)
                cycle = path[cycle_start:] + [node]
                cycles.append(cycle)
                return True
            
            if node in visited:
                return False
            
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            for neighbor in self.dependency_graph.get(node, []):
                dfs(neighbor, path.copy())
            
            rec_stack.remove(node)
            return False
        
        for node in self.dependency_graph:
            if node not in visited:
                dfs(node, [])
        
        return cycles
    
    def get_layer(self, module_name: str) -> Optional[str]:
        """Get the architectural layer of a module."""
        parts = module_name.split('.')
        if len(parts) >= 2 and parts[0] == 'backend':
            layer = parts[1]
            if layer in self.layers:
                return layer
        return None
    
    def check_architectural_violations(self):
        """Check for violations of architectural layer rules.
        
        This function iterates through the dependency graph to identify any
        architectural violations based on defined layer rules. For each module,  it
        retrieves its layer and checks the layers of its dependencies. If a
        dependency's layer is not allowed to be imported by the module's layer,  an
        ArchitecturalViolation is recorded, detailing the violator, target,  and the
        nature of the violation.
        """
        self.architectural_violations = []
        
        for module, dependencies in self.dependency_graph.items():
            module_layer = self.get_layer(module)
            if not module_layer:
                continue
                
            for dep_module in dependencies:
                dep_layer = self.get_layer(dep_module)
                if not dep_layer:
                    continue
                
                # Check if this import violates layer rules
                allowed_imports = self.layers[module_layer]['can_import']
                
                if dep_layer not in allowed_imports:
                    # Check if it's a same-layer import (usually allowed)
                    if dep_layer != module_layer:
                        self.architectural_violations.append(ArchitecturalViolation(
                            violator=module,
                            target=dep_module,
                            violation_type="layer_violation",
                            description=f"{module_layer} layer importing from {dep_layer} layer"
                        ))
    
    def analyze(self):
        """Run the complete analysis of the backend architecture."""
        print(f"Analyzing backend architecture in {self.backend_path}")
        
        # Find all Python files
        python_files = list(self.backend_path.rglob("*.py"))
        print(f"Found {len(python_files)} Python files")
        
        # Analyze each file
        for file_path in python_files:
            self.analyze_file(file_path)
        
        print(f"Analyzed {len(self.module_imports)} modules")
        
        # Find circular dependencies
        cycles = self.find_cycles()
        self.circular_dependencies = [
            CircularDependency(cycle=cycle, strength=len(cycle))
            for cycle in cycles
        ]
        
        print(f"Found {len(self.circular_dependencies)} circular dependencies")
        
        # Check architectural violations
        self.check_architectural_violations()
        print(f"Found {len(self.architectural_violations)} architectural violations")
    
    def get_import_analysis(self) -> Dict[str, Any]:
        """Get detailed import analysis statistics.
        
        This function analyzes the dependency graph to gather statistics on module
        imports. It counts the most imported and most importing modules, identifies
        external dependencies, and checks for modules that only have internal
        dependencies. The results are compiled into a dictionary containing these
        statistics.
        
        Returns:
            Dict[str, Any]: A dictionary with keys for most imported modules, most importing modules,
                external dependencies, internal dependencies only, and dependency depth.
        """
        stats = {
            'most_imported_modules': {},
            'most_importing_modules': {},
            'external_dependencies': set(),
            'internal_dependencies_only': [],
            'dependency_depth': {}
        }
        
        # Count incoming dependencies
        for module, deps in self.dependency_graph.items():
            for dep in deps:
                if dep in stats['most_imported_modules']:
                    stats['most_imported_modules'][dep] += 1
                else:
                    stats['most_imported_modules'][dep] = 1
        
        # Count outgoing dependencies
        for module, deps in self.dependency_graph.items():
            stats['most_importing_modules'][module] = len(deps)
            
            # Check for external dependencies
            for import_info in self.module_imports.get(module, []):
                if not import_info.is_relative and not import_info.module.startswith('backend.'):
                    stats['external_dependencies'].add(import_info.module)
            
            # Check if module only has internal dependencies
            if all(dep.startswith('backend.') for dep in deps):
                stats['internal_dependencies_only'].append(module)
        
        return stats

    def generate_report(self) -> str:
        """Generate a comprehensive analysis report of the project's dependencies.
        
        This function constructs a detailed report that includes circular dependency
        analysis, architectural violations, and import statistics. It aggregates data
        from various sources, including `self.get_import_analysis()`, and formats the
        findings into a structured output. The report covers total modules analyzed,
        dependencies, and highlights any architectural issues, providing insights into
        the project's structure and potential problems.
        
        Args:
            self: The instance of the class containing the report generation logic.
        
        Returns:
            str: A formatted string containing the analysis report.
        """
        report = []
        report.append("="*80)
        report.append("CIRCULAR DEPENDENCY ANALYSIS REPORT")
        report.append("="*80)
        report.append(f"Generated: {datetime.now().isoformat()}")
        report.append(f"Backend Path: {self.backend_path}")
        report.append("")
        
        # Get import analysis
        import_stats = self.get_import_analysis()
        
        # Summary
        report.append("SUMMARY")
        report.append("-"*40)
        report.append(f"Total Modules Analyzed: {len(self.module_imports)}")
        report.append(f"Total Dependencies: {sum(len(deps) for deps in self.dependency_graph.values())}")
        report.append(f"Circular Dependencies: {len(self.circular_dependencies)}")
        report.append(f"Architectural Violations: {len(self.architectural_violations)}")
        report.append(f"External Dependencies: {len(import_stats['external_dependencies'])}")
        report.append("")
        
        # Circular Dependencies
        if self.circular_dependencies:
            report.append("CIRCULAR DEPENDENCIES")
            report.append("-"*40)
            for i, cycle in enumerate(self.circular_dependencies, 1):
                report.append(f"{i}. Cycle (strength: {cycle.strength})")
                for j, module in enumerate(cycle.cycle):
                    if j < len(cycle.cycle) - 1:
                        report.append(f"   {module} → {cycle.cycle[j+1]}")
                report.append("")
        else:
            report.append("✅ NO CIRCULAR DEPENDENCIES FOUND")
            report.append("")
        
        # Architectural Violations
        if self.architectural_violations:
            report.append("ARCHITECTURAL VIOLATIONS")
            report.append("-"*40)
            for i, violation in enumerate(self.architectural_violations, 1):
                report.append(f"{i}. {violation.violation_type.upper()}")
                report.append(f"   Violator: {violation.violator}")
                report.append(f"   Target:   {violation.target}")
                report.append(f"   Issue:    {violation.description}")
                report.append("")
        else:
            report.append("✅ NO ARCHITECTURAL VIOLATIONS FOUND")
            report.append("")
        
        # Import Analysis
        report.append("DEPENDENCY ANALYSIS")
        report.append("-"*40)
        
        # Most imported modules (dependency hotspots)
        most_imported = sorted(import_stats['most_imported_modules'].items(), 
                              key=lambda x: x[1], reverse=True)[:10]
        if most_imported:
            report.append("Most Imported Modules (Dependency Hotspots):")
            for module, count in most_imported:
                report.append(f"  {module} ({count} imports)")
            report.append("")
        
        # Most importing modules (high fan-out)
        most_importing = sorted(import_stats['most_importing_modules'].items(),
                               key=lambda x: x[1], reverse=True)[:10]
        if most_importing:
            report.append("Modules with Most Dependencies (High Fan-out):")
            for module, count in most_importing:
                if count > 0:
                    report.append(f"  {module} ({count} dependencies)")
            report.append("")
        
        # External dependencies
        if import_stats['external_dependencies']:
            report.append("External Dependencies:")
            for dep in sorted(import_stats['external_dependencies']):
                report.append(f"  - {dep}")
            report.append("")
        
        # Module Dependencies
        report.append("MODULE DEPENDENCY DETAILS")
        report.append("-"*40)
        for module in sorted(self.dependency_graph.keys()):
            dependencies = sorted(self.dependency_graph[module])
            if dependencies:
                report.append(f"{module}")
                for dep in dependencies:
                    report.append(f"  → {dep}")
                report.append("")
        
        # Architectural Layers
        report.append("ARCHITECTURAL LAYER ANALYSIS")
        report.append("-"*40)
        layer_modules = defaultdict(list)
        for module in self.module_imports:
            layer = self.get_layer(module)
            if layer:
                layer_modules[layer].append(module)
        
        for layer in sorted(self.layers.keys(), key=lambda x: self.layers[x]['level'], reverse=True):
            if layer in layer_modules:
                report.append(f"{layer.upper()} LAYER (Level {self.layers[layer]['level']})")
                report.append(f"  Can import from: {', '.join(self.layers[layer]['can_import'])}")
                report.append(f"  Modules ({len(layer_modules[layer])}):")
                for module in sorted(layer_modules[layer]):
                    report.append(f"    - {module}")
                report.append("")
        
        return "\n".join(report)
    
    def export_json(self, output_path: str):
        """Export analysis results to JSON format.
        
        This function gathers various analysis results, including the analysis date,
        backend path, summary statistics, circular dependencies, architectural
        violations,  and the dependency graph. It then serializes this data into a JSON
        format and  writes it to the specified output_path. The function ensures that
        the output is  properly formatted and encoded in UTF-8.
        
        Args:
            output_path (str): The file path where the JSON data will be saved.
        """
        data = {
            "analysis_date": datetime.now().isoformat(),
            "backend_path": str(self.backend_path),
            "summary": {
                "total_modules": len(self.module_imports),
                "total_dependencies": sum(len(deps) for deps in self.dependency_graph.values()),
                "circular_dependencies_count": len(self.circular_dependencies),
                "architectural_violations_count": len(self.architectural_violations)
            },
            "circular_dependencies": [
                {
                    "cycle": cd.cycle,
                    "strength": cd.strength
                } for cd in self.circular_dependencies
            ],
            "architectural_violations": [
                {
                    "violator": av.violator,
                    "target": av.target,
                    "violation_type": av.violation_type,
                    "description": av.description
                } for av in self.architectural_violations
            ],
            "dependency_graph": {
                module: list(deps) for module, deps in self.dependency_graph.items()
            },
            "module_imports": {
                module: [
                    {
                        "module": imp.module,
                        "from_module": imp.from_module,
                        "alias": imp.alias,
                        "line_number": imp.line_number,
                        "is_relative": imp.is_relative
                    } for imp in imports
                ] for module, imports in self.module_imports.items()
            }
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def main():
    """Main execution function for analyzing circular dependencies.
    
    This function checks for the existence of a specified backend path,
    initializes a CircularDependencyAnalyzer with that path, and performs  an
    analysis. It generates a report in both text and JSON formats,  saving them to
    predefined locations. The function also prints the  report and the paths where
    the reports are saved. It returns a  non-zero value if any circular
    dependencies or architectural  violations are found during the analysis.
    """
    if len(sys.argv) > 1:
        backend_path = sys.argv[1]
    else:
        backend_path = "/home/yan/A101/HR/backend"
    
    if not os.path.exists(backend_path):
        print(f"Error: Backend path {backend_path} does not exist")
        return 1
    
    analyzer = CircularDependencyAnalyzer(backend_path)
    analyzer.analyze()
    
    # Generate and save report
    report = analyzer.generate_report()
    
    # Save text report
    report_path = "/home/yan/A101/HR/scripts/circular_dependency_report.txt"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    
    # Save JSON report
    json_path = "/home/yan/A101/HR/scripts/circular_dependency_analysis.json"
    analyzer.export_json(json_path)
    
    print(report)
    print(f"\nReports saved to:")
    print(f"  Text: {report_path}")
    print(f"  JSON: {json_path}")
    
    # Return non-zero if issues found
    if analyzer.circular_dependencies or analyzer.architectural_violations:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())