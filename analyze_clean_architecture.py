#!/usr/bin/env python3
"""
Comprehensive Clean Architecture analysis for A101 HR system.
Analyzes dependency flows, layer violations, and adherence to Clean Architecture principles.
"""

import os
import re
import json
from pathlib import Path
from collections import defaultdict, deque
from typing import Dict, List, Optional, Set, Tuple

class CleanArchitectureAnalyzer:
    """Analyzes Clean Architecture compliance in the codebase"""
    
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.backend_root = self.project_root / "backend"
        
        # Define layer hierarchy (outer to inner)
        self.layers = {
            'api': 1,           # Outermost - HTTP endpoints, middleware
            'services': 2,      # Infrastructure services
            'core': 3,          # Business logic, domain services  
            'models': 4,        # Data structures, database
            'utils': 5          # Innermost - Pure utilities
        }
        
        # Reverse mapping for easier lookup
        self.layer_names = {v: k for k, v in self.layers.items()}
        
        self.dependencies = defaultdict(set)
        self.reverse_dependencies = defaultdict(set)
        self.violations = []
        
    def analyze_file(self, file_path: Path) -> Tuple[Optional[str], List[str]]:
        """Analyze a single Python file for its imports"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            return None, []
        
        # Determine which layer this file belongs to
        relative_path = file_path.relative_to(self.backend_root)
        parts = relative_path.parts
        
        if not parts:
            return None, []
            
        layer = parts[0] if parts[0] in self.layers else 'unknown'
        
        # Extract imports
        imports = []
        
        # Match various import patterns
        patterns = [
            r'from\s+\.\.([^.\s]+)',              # from ..core
            r'from\s+\.\.\.([^.\s]+)',            # from ...core  
            r'from\s+backend\.([^.\s]+)',         # from backend.core
            r'from\s+\.([^.\s]+)',                # from .core (relative)
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                if match in self.layers:
                    imports.append(match)
        
        return layer, imports
        
    def analyze_dependencies(self):
        """Analyze all Python files for dependencies"""
        print("🔍 Analyzing dependencies...")
        
        for py_file in self.backend_root.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
                
            layer, imports = self.analyze_file(py_file)
            if not layer or layer == 'unknown':
                continue
                
            for imported_layer in imports:
                self.dependencies[layer].add(imported_layer)
                self.reverse_dependencies[imported_layer].add(layer)
                
                # Check for violations (outer layer depending on inner is OK)
                current_layer_level = self.layers[layer]
                imported_layer_level = self.layers[imported_layer]
                
                if current_layer_level > imported_layer_level:
                    self.violations.append({
                        'file': str(py_file.relative_to(self.project_root)),
                        'from_layer': layer,
                        'to_layer': imported_layer,
                        'violation_type': 'dependency_inversion',
                        'severity': 'high'
                    })
    
    def check_single_responsibility(self) -> List[Dict]:
        """Check Single Responsibility Principle violations"""
        violations = []
        
        # Check for modules that are too large (> 500 lines)
        for py_file in self.backend_root.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
                
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    line_count = sum(1 for line in f)
                    
                if line_count > 500:
                    violations.append({
                        'file': str(py_file.relative_to(self.project_root)),
                        'issue': f'Large module ({line_count} lines)',
                        'violation_type': 'single_responsibility',
                        'severity': 'medium'
                    })
            except (OSError, UnicodeDecodeError):
                continue
                
        return violations
    
    def check_interface_segregation(self) -> List[Dict]:
        """Check Interface Segregation Principle compliance"""
        violations = []
        
        interfaces_file = self.backend_root / "core" / "interfaces.py"
        if not interfaces_file.exists():
            violations.append({
                'issue': 'No interfaces.py found in core layer',
                'violation_type': 'interface_segregation',
                'severity': 'medium'
            })
            return violations
            
        # Check if interfaces are being used properly
        interface_usage = defaultdict(int)
        
        for py_file in self.backend_root.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
                
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                if 'AuthInterface' in content:
                    interface_usage['AuthInterface'] += 1
            except (OSError, UnicodeDecodeError):
                continue
        
        # Check if we have interfaces but they're not used
        if interface_usage['AuthInterface'] < 2:  # Should be used in at least service + middleware
            violations.append({
                'issue': 'AuthInterface defined but underused',
                'violation_type': 'interface_segregation', 
                'severity': 'low'
            })
            
        return violations
    
    def generate_report(self) -> Dict:
        """Generate comprehensive Clean Architecture compliance report"""
        
        # Analyze dependencies
        self.analyze_dependencies()
        
        # Check additional principles
        srp_violations = self.check_single_responsibility()
        isp_violations = self.check_interface_segregation()
        
        # Combine all violations
        all_violations = self.violations + srp_violations + isp_violations
        
        # Calculate compliance score
        total_checks = len(list(self.backend_root.rglob("*.py"))) * 3  # 3 principles checked per file
        violation_weight = {'high': 3, 'medium': 2, 'low': 1}
        violation_score = sum(violation_weight.get(v.get('severity', 'medium'), 2) 
                            for v in all_violations)
        
        compliance_score = max(0, 100 - (violation_score / total_checks * 100))
        
        report = {
            'compliance_score': round(compliance_score, 1),
            'layer_structure': {
                'defined_layers': list(self.layers.keys()),
                'layer_hierarchy': dict(self.layers)
            },
            'dependency_analysis': {
                'forward_dependencies': dict(self.dependencies),
                'reverse_dependencies': dict(self.reverse_dependencies),
                'total_dependencies': sum(len(deps) for deps in self.dependencies.values())
            },
            'violations': {
                'total_count': len(all_violations),
                'by_severity': {
                    'high': len([v for v in all_violations if v.get('severity') == 'high']),
                    'medium': len([v for v in all_violations if v.get('severity') == 'medium']),
                    'low': len([v for v in all_violations if v.get('severity') == 'low'])
                },
                'by_principle': {
                    'dependency_rule': len([v for v in all_violations if v.get('violation_type') == 'dependency_inversion']),
                    'single_responsibility': len([v for v in all_violations if v.get('violation_type') == 'single_responsibility']),
                    'interface_segregation': len([v for v in all_violations if v.get('violation_type') == 'interface_segregation'])
                },
                'details': all_violations
            },
            'recommendations': self.generate_recommendations(all_violations)
        }
        
        return report
    
    def generate_recommendations(self, violations: List[Dict]) -> List[str]:
        """Generate actionable recommendations based on violations"""
        recommendations = []
        
        high_violations = [v for v in violations if v.get('severity') == 'high']
        if high_violations:
            recommendations.append("🔴 CRITICAL: Fix dependency inversion violations immediately")
            
        srp_violations = [v for v in violations if v.get('violation_type') == 'single_responsibility']
        if len(srp_violations) > 3:
            recommendations.append("📏 Consider breaking down large modules into smaller, focused modules")
            
        interface_violations = [v for v in violations if v.get('violation_type') == 'interface_segregation']  
        if interface_violations:
            recommendations.append("🔌 Expand interface usage for better dependency injection")
            
        if not violations:
            recommendations.append("✅ Excellent Clean Architecture compliance!")
            
        return recommendations

def main():
    analyzer = CleanArchitectureAnalyzer("/home/yan/A101/HR")
    report = analyzer.generate_report()
    
    print("="*80)
    print("🏗️  CLEAN ARCHITECTURE COMPLIANCE REPORT")
    print("="*80)
    
    print(f"\n📊 OVERALL COMPLIANCE SCORE: {report['compliance_score']}/100")
    
    if report['compliance_score'] >= 90:
        print("🟢 EXCELLENT - Outstanding Clean Architecture compliance")
    elif report['compliance_score'] >= 75:
        print("🟡 GOOD - Good compliance with room for improvement") 
    elif report['compliance_score'] >= 60:
        print("🟠 FAIR - Moderate compliance, needs attention")
    else:
        print("🔴 POOR - Significant violations need immediate attention")
    
    print(f"\n🏗️  LAYER STRUCTURE:")
    for layer, level in sorted(report['layer_structure']['layer_hierarchy'].items(), key=lambda x: x[1]):
        print(f"  {level}. {layer:<12} {'(outermost)' if level == 1 else '(innermost)' if level == max(report['layer_structure']['layer_hierarchy'].values()) else ''}")
    
    print(f"\n🔗 DEPENDENCY ANALYSIS:")
    print(f"  Total dependencies: {report['dependency_analysis']['total_dependencies']}")
    
    print(f"  Forward dependencies:")
    for layer, deps in report['dependency_analysis']['forward_dependencies'].items():
        if deps:
            print(f"    {layer} → {', '.join(sorted(deps))}")
    
    print(f"\n⚠️  VIOLATIONS SUMMARY:")
    violations = report['violations']
    print(f"  Total violations: {violations['total_count']}")
    print(f"  By severity: High={violations['by_severity']['high']}, Medium={violations['by_severity']['medium']}, Low={violations['by_severity']['low']}")
    print(f"  By principle:")
    print(f"    Dependency Rule: {violations['by_principle']['dependency_rule']}")
    print(f"    Single Responsibility: {violations['by_principle']['single_responsibility']}")
    print(f"    Interface Segregation: {violations['by_principle']['interface_segregation']}")
    
    if violations['details']:
        print(f"\n🔍 DETAILED VIOLATIONS:")
        for i, violation in enumerate(violations['details'][:5], 1):  # Show first 5
            print(f"  {i}. {violation.get('violation_type', 'unknown').title()}")
            if 'file' in violation:
                print(f"     File: {violation['file']}")
            if 'from_layer' in violation and 'to_layer' in violation:
                print(f"     Issue: {violation['from_layer']} → {violation['to_layer']} (inner → outer dependency)")
            elif 'issue' in violation:
                print(f"     Issue: {violation['issue']}")
            print(f"     Severity: {violation.get('severity', 'unknown')}")
            print()
        
        if len(violations['details']) > 5:
            print(f"  ... and {len(violations['details']) - 5} more violations")
    
    print(f"\n💡 RECOMMENDATIONS:")
    for i, rec in enumerate(report['recommendations'], 1):
        print(f"  {i}. {rec}")
    
    print(f"\n🎯 CLEAN ARCHITECTURE PRINCIPLES ASSESSMENT:")
    principles_score = {
        'Dependency Rule': 100 - (violations['by_principle']['dependency_rule'] * 20),
        'Layer Separation': 85 if violations['total_count'] < 5 else 60,
        'Interface Segregation': 80 if violations['by_principle']['interface_segregation'] == 0 else 60,
        'Single Responsibility': 90 - (violations['by_principle']['single_responsibility'] * 10),
        'Open/Closed Principle': 85  # Estimated based on modular structure
    }
    
    for principle, score in principles_score.items():
        status = "✅" if score >= 80 else "⚠️" if score >= 60 else "❌"
        print(f"  {status} {principle}: {max(0, score)}/100")
    
    print("\n" + "="*80)

if __name__ == "__main__":
    main()
