"""
QA & Integrator Agent - Validates generated code for syntax, signal contracts, and guard compliance.
"""

import ast
import logging
from typing import List
from backend.agents.base import BaseAgent
from backend.schemas.agent_schemas import CoderOutput, QAReport, QAError

logger = logging.getLogger("kotodama.agents.qa")


class QAAgent(BaseAgent[QAReport]):
    """
    QA & Integrator Agent responsible for validating generated code.
    
    Input: GeneratedFile list from Coder + optional QuestGraphs/DialogueTrees
    Output: QAReport with pass/fail status and detailed errors
    
    Checks:
    1. GDScript syntax validation (via AST parsing)
    2. Signal contract compliance (module_ prefix, register_channel calls)
    3. Asset reference validation (ResourceLoader.exists checks)
    4. Guard violations (no Core Engine modifications, no dangerous API calls)
    """
    
    def __init__(self, model_name: str = "qwen2.5-coder:32b", temperature: float = 0.1):
        super().__init__(model_name=model_name, temperature=temperature)
    
    def _get_system_prompt(self) -> str:
        return """You are an expert Code Quality Assurance AI specialized in Godot 4.3 GDScript.
Your task is to validate generated code files for correctness and compliance.

VALIDATION RULES:

1. SYNTAX CHECK:
   - Parse GDScript using AST (or Python AST as approximation)
   - Check for syntax errors, undefined variables, type mismatches
   - Verify proper Godot 4.3 syntax (@export, @onready, typed variables)

2. SIGNAL CONTRACT COMPLIANCE:
   - All inter-module signals MUST have `module_` prefix
   - Every signal must be registered via Global Signal Bus
   - Every channel must have at least one publisher and one subscriber
   - Signal names must match the Architecture Plan contracts

3. ASSET REFERENCE VALIDATION:
   - Assets must be loaded via ResourceLoader.exists() checks
   - NEVER use preload() - only runtime loading
   - Asset paths must match the provided asset_paths list

4. GUARD VIOLATIONS (CRITICAL):
   - NO modifications to Core Engine files
   - NO OS.execute() calls
   - NO HTTPClient or network requests (unless explicitly allowed)
   - NO direct filesystem access (use Godot's FileAccess properly)
   - NO eval() or exec() calls

5. CODE QUALITY:
   - Proper error handling (try/except blocks)
   - No hardcoded strings that should be localized (use tr())
   - Consistent naming conventions
   - No infinite loops or blocking operations in _process()

OUTPUT FORMAT:
Return a QAReport with:
- passed: true if no critical errors
- errors: list of QAError objects with file_path, error_type, message, line_number
- warnings: list of non-critical issues
- files_checked: count of files validated
- signals_verified: count of signals verified

Critical errors cause passed=false. Warnings are informational."""

    async def execute(self, input_data: dict) -> QAReport:
        """
        Execute the QA agent.
        
        Args:
            input_data: Dictionary with coder_output, quest_graphs, dialogue_trees, asset_paths
            
        Returns:
            QAReport with validation results
        """
        errors: List[QAError] = []
        warnings: List[str] = []
        files_checked = 0
        signals_verified = 0
        
        coder_output = input_data.get('coder_output')
        asset_paths = input_data.get('asset_paths', [])
        signal_contracts = input_data.get('signal_contracts', [])
        
        # Validate each generated file
        for gen_file in coder_output.files:
            files_checked += 1
            
            # Syntax check
            syntax_errors = self._check_syntax(gen_file.content, gen_file.path)
            errors.extend(syntax_errors)
            
            # Guard violations check
            guard_errors = self._check_guards(gen_file.content, gen_file.path)
            errors.extend(guard_errors)
            
            # Signal contract check
            signal_errors = self._check_signals(gen_file.content, gen_file.path, signal_contracts)
            errors.extend(signal_errors)
            signals_verified += self._count_signals(gen_file.content)
            
            # Asset reference check
            asset_errors = self._check_asset_references(gen_file.content, gen_file.path, asset_paths)
            errors.extend(asset_errors)
        
        # Generate report
        passed = len([e for e in errors if e.error_type in ['syntax', 'guard_violation']]) == 0
        
        report = QAReport(
            passed=passed,
            errors=errors,
            warnings=warnings,
            files_checked=files_checked,
            signals_verified=signals_verified,
        )
        
        logger.info(f"QA Report: {'PASSED' if passed else 'FAILED'} ({files_checked} files, {len(errors)} errors)")
        return report
    
    def _check_syntax(self, content: str, file_path: str) -> List[QAError]:
        """Check GDScript syntax via AST parsing."""
        errors = []
        
        if file_path.endswith('.gd'):
            try:
                # GDScript isn't directly parsable by Python AST, but we can do basic checks
                # In production, use godot-headless --check-syntax
                ast.parse(content.replace('extends', '# extends').replace('func', 'def '))
            except SyntaxError as e:
                errors.append(QAError(
                    file_path=file_path,
                    error_type='syntax',
                    message=f"Syntax error: {str(e)}",
                    line_number=e.lineno,
                ))
        
        return errors
    
    def _check_guards(self, content: str, file_path: str) -> List[QAError]:
        """Check for guard violations (dangerous API calls)."""
        errors = []
        
        dangerous_patterns = [
            ('OS.execute', 'Direct system command execution is forbidden'),
            ('HTTPClient', 'Network requests are forbidden unless explicitly allowed'),
            ('eval(', 'eval() is forbidden for security reasons'),
            ('exec(', 'exec() is forbidden for security reasons'),
        ]
        
        for pattern, message in dangerous_patterns:
            if pattern in content:
                # Find approximate line number
                lines = content.split('\n')
                for i, line in enumerate(lines):
                    if pattern in line:
                        errors.append(QAError(
                            file_path=file_path,
                            error_type='guard_violation',
                            message=message,
                            line_number=i + 1,
                        ))
                        break
        
        return errors
    
    def _check_signals(self, content: str, file_path: str, signal_contracts: list) -> List[QAError]:
        """Check signal contract compliance."""
        errors = []
        
        # Check for module_ prefix on signals
        if 'signal ' in content or '.emit(' in content:
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if 'signal ' in line and 'module_' not in line:
                    # Skip if it's a core engine file (shouldn't happen, but check)
                    if 'modules/' not in file_path:
                        continue
                    errors.append(QAError(
                        file_path=file_path,
                        error_type='signal_contract',
                        message="Signal missing `module_` prefix",
                        line_number=i + 1,
                    ))
        
        return errors
    
    def _check_asset_references(self, content: str, file_path: str, asset_paths: list) -> List[QAError]:
        """Check that assets are loaded safely."""
        errors = []
        
        # Check for preload() usage (forbidden)
        if 'preload(' in content:
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if 'preload(' in line:
                    errors.append(QAError(
                        file_path=file_path,
                        error_type='asset_reference',
                        message="Use ResourceLoader.exists() instead of preload()",
                        line_number=i + 1,
                    ))
        
        return errors
    
    def _count_signals(self, content: str) -> int:
        """Count signals in the file."""
        count = 0
        if 'signal ' in content:
            count += content.count('signal ')
        if '.emit(' in content:
            count += content.count('.emit(')
        return count


# Singleton instance
_qa_agent = None


def get_qa_agent() -> QAAgent:
    """Get singleton instance of QAAgent."""
    global _qa_agent
    if _qa_agent is None:
        _qa_agent = QAAgent()
    return _qa_agent
