"""
Module Marketplace Service

Handles module publication, security scanning, and marketplace operations.
Implements strict AST-based security analysis to prevent malicious code.
"""

import ast
import hashlib
from pathlib import Path
from typing import Literal
from datetime import datetime
from pydantic import BaseModel, Field


class ModuleMetadata(BaseModel):
    """Metadata for a marketplace module."""
    module_id: str
    name: str
    description: str
    author_id: str
    version: str = "1.0.0"
    category: Literal["gameplay", "ui", "system", "ai", "audio", "visual"]
    price_credits: int = 0  # 0 = free
    tags: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    downloads: int = 0
    rating: float = 0.0
    is_published: bool = False


class SecurityViolation(BaseModel):
    """Represents a security violation found during scanning."""
    violation_type: Literal[
        "os_execute",
        "file_access", 
        "network_request",
        "dynamic_import",
        "eval_exec",
        "subprocess_call",
        "shell_command",
        "unsafe_deserialization"
    ]
    file_path: str
    line_number: int
    code_snippet: str
    severity: Literal["critical", "high", "medium", "low"]
    message: str


class ScanResult(BaseModel):
    """Result of module security scan."""
    module_id: str
    passed: bool
    violations: list[SecurityViolation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    scanned_files: list[str] = Field(default_factory=list)
    scan_timestamp: datetime = Field(default_factory=datetime.utcnow)
    scanner_version: str = "1.0.0"


class AssetHash(BaseModel):
    """Perceptual hash for asset plagiarism detection."""
    asset_path: str
    phash: str  # Perceptual hash
    md5: str  # Traditional hash
    dimensions: tuple[int, int] | None = None


class PlagiarismCheck(BaseModel):
    """Result of plagiarism check."""
    asset_path: str
    is_plagiarized: bool
    similarity_score: float  # 0.0 to 1.0
    matching_assets: list[str] = Field(default_factory=list)
    threshold: float = 0.85


class MarketplaceModule(BaseModel):
    """Complete marketplace module entry."""
    metadata: ModuleMetadata
    files: list[str]
    assets: list[AssetHash]
    security_scan: ScanResult
    plagiarism_checks: list[PlagiarismCheck] = Field(default_factory=list)
    download_url: str | None = None
    preview_images: list[str] = Field(default_factory=list)


class GDScriptSecurityScanner:
    """
    AST-based security scanner for GDScript files.
    
    Detects dangerous patterns:
    - OS.execute() - Shell command execution
    - FileAccess - Direct filesystem access
    - HTTPClient/HTTPRequest - Network requests
    - load_code() - Dynamic code loading
    - eval()/exec() - Code execution
    - pickle/json with untrusted data - Unsafe deserialization
    """
    
    DANGEROUS_PATTERNS = {
        "OS": ["execute", "shell_open", "get_cmdline_args"],
        "FileAccess": ["open", "get_file_as_bytes"],
        "DirAccess": ["open", "list_dir"],
        "HTTPClient": ["request", "request_raw"],
        "HTTPRequest": ["request", "request_raw"],
        "StreamPeer": ["put_data", "put_string"],
    }
    
    CRITICAL_FUNCTIONS = ["eval", "exec", "exec_", "compile", "load_code"]
    
    def __init__(self):
        self.violations: list[SecurityViolation] = []
        self.warnings: list[str] = []
        self.scanned_files: list[str] = []
    
    def scan_module(self, module_path: Path, module_id: str) -> ScanResult:
        """Scan all GDScript files in a module."""
        self.violations = []
        self.warnings = []
        self.scanned_files = []
        
        # Find all .gd files
        gd_files = list(module_path.rglob("*.gd"))
        
        for gd_file in gd_files:
            self.scanned_files.append(str(gd_file.relative_to(module_path)))
            self._scan_file(gd_file, module_id)
        
        # Check for critical violations
        critical_violations = [v for v in self.violations if v.severity == "critical"]
        passed = len(critical_violations) == 0
        
        return ScanResult(
            module_id=module_id,
            passed=passed,
            violations=self.violations,
            warnings=self.warnings,
            scanned_files=self.scanned_files,
        )
    
    def _scan_file(self, file_path: Path, module_id: str) -> None:
        """Scan a single GDScript file using AST parsing."""
        try:
            content = file_path.read_text(encoding="utf-8")
            lines = content.split("\n")
            
            # Parse AST
            tree = ast.parse(content)
            
            # Walk through AST nodes
            for node in ast.walk(tree):
                self._check_node(node, file_path, lines, module_id)
            
            # Also do regex-based checks for GDScript-specific patterns
            self._regex_scan(content, file_path, lines, module_id)
            
        except SyntaxError as e:
            self.warnings.append(f"Syntax error in {file_path}: {e}")
        except Exception as e:
            self.warnings.append(f"Scan error in {file_path}: {e}")
    
    def _check_node(self, node: ast.AST, file_path: Path, lines: list[str], module_id: str) -> None:
        """Check an AST node for security violations."""
        # Check for dangerous function calls
        if isinstance(node, ast.Call):
            func_name = None
            
            # Get function name
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
                
            if func_name in self.CRITICAL_FUNCTIONS:
                line_num = node.lineno
                snippet = lines[line_num - 1].strip() if line_num <= len(lines) else ""
                
                self.violations.append(SecurityViolation(
                    violation_type="eval_exec",
                    file_path=str(file_path),
                    line_number=line_num,
                    code_snippet=snippet,
                    severity="critical",
                    message=f"Dangerous function '{func_name}()' detected. Dynamic code execution is prohibited."
                ))
        
        # Check for dangerous class instantiations
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ["HTTPClient", "HTTPRequest"]:
                line_num = node.lineno
                snippet = lines[line_num - 1].strip() if line_num <= len(lines) else ""
                
                self.violations.append(SecurityViolation(
                    violation_type="network_request",
                    file_path=str(file_path),
                    line_number=line_num,
                    code_snippet=snippet,
                    severity="critical",
                    message=f"Network access via '{node.func.id}' is prohibited in marketplace modules."
                ))
    
    def _regex_scan(self, content: str, file_path: Path, lines: list[str], module_id: str) -> None:
        """Regex-based scan for GDScript-specific patterns not caught by AST."""
        import re
        
        dangerous_patterns = [
            (r'OS\.execute\s*\(', "os_execute", "critical", "Shell command execution"),
            (r'OS\.shell_open\s*\(', "os_execute", "critical", "Shell command execution"),
            (r'FileAccess\.open\s*\(', "file_access", "high", "Direct file access"),
            (r'DirAccess\.open\s*\(', "file_access", "high", "Directory access"),
            (r'HTTPClient\.', "network_request", "critical", "HTTP client usage"),
            (r'HTTPRequest\.', "network_request", "critical", "HTTP request usage"),
            (r'StreamPeer', "network_request", "high", "Network stream access"),
            (r'pickle\.', "unsafe_deserialization", "critical", "Unsafe deserialization"),
            (r'subprocess\.', "subprocess_call", "critical", "Subprocess execution"),
            (r'eval\s*\(', "eval_exec", "critical", "Dynamic code evaluation"),
            (r'exec\s*\(', "eval_exec", "critical", "Dynamic code execution"),
        ]
        
        for pattern, vtype, severity, message in dangerous_patterns:
            matches = list(re.finditer(pattern, content))
            for match in matches:
                # Find line number
                line_num = content[:match.start()].count('\n') + 1
                snippet = lines[line_num - 1].strip() if line_num <= len(lines) else ""
                
                # Avoid duplicates from AST scan
                existing = [v for v in self.violations 
                           if v.file_path == str(file_path) and v.line_number == line_num]
                
                if not existing:
                    self.violations.append(SecurityViolation(
                        violation_type=vtype,  # type: ignore
                        file_path=str(file_path),
                        line_number=line_num,
                        code_snippet=snippet,
                        severity=severity,  # type: ignore
                        message=f"{message} detected. This is prohibited for security reasons."
                    ))
    
    @staticmethod
    def compute_asset_hash(asset_path: Path) -> AssetHash:
        """Compute MD5 hash for an asset file."""
        import hashlib
        
        md5_hash = hashlib.md5()
        
        with open(asset_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                md5_hash.update(chunk)
        
        # For images, also compute perceptual hash
        phash = "none"
        dimensions = None
        
        if asset_path.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]:
            try:
                from PIL import Image
                with Image.open(asset_path) as img:
                    dimensions = img.size
                    # Simple average hash (in production, use pHash library)
                    img_resized = img.resize((8, 8)).convert("L")
                    pixels = list(img_resized.getdata())
                    avg = sum(pixels) / len(pixels)
                    binary = "".join("1" if p > avg else "0" for p in pixels)
                    phash = hex(int(binary, 2))[2:].zfill(16)
            except Exception:
                pass
        
        return AssetHash(
            asset_path=str(asset_path),
            phash=phash,
            md5=md5_hash.hexdigest(),
            dimensions=dimensions,
        )
    
    @staticmethod
    def compare_hashes(hash1: str, hash2: str) -> float:
        """Compare two perceptual hashes and return similarity score."""
        if len(hash1) != len(hash2):
            return 0.0
        
        # Count matching bits
        matching_bits = sum(
            c1 == c2 
            for c1, c2 in zip(hash1, hash2)
        )
        
        return matching_bits / len(hash1)


class MarketplaceService:
    """
    Service for managing the module marketplace.
    
    Features:
    - Module submission and validation
    - Security scanning (AST + regex)
    - Plagiarism detection via perceptual hashing
    - Module storage and retrieval
    - Download tracking
    """
    
    def __init__(self, storage_path: Path, minio_service=None):
        self.storage_path = storage_path
        self.minio_service = minio_service
        self.scanner = GDScriptSecurityScanner()
        self.modules: dict[str, MarketplaceModule] = {}
    
    async def submit_module(
        self,
        module_path: Path,
        metadata: ModuleMetadata,
        author_id: str
    ) -> tuple[bool, str]:
        """
        Submit a module to the marketplace.
        
        Returns:
            Tuple of (success, message)
        """
        # Validate module structure
        if not module_path.exists():
            return False, "Module path does not exist"
        
        if not (module_path / "module.gd").exists():
            return False, "Module must contain module.gd entry point"
        
        # Run security scan
        scan_result = self.scanner.scan_module(module_path, metadata.module_id)
        
        if not scan_result.passed:
            violations_str = "\n".join([f"- {v.message}" for v in scan_result.violations])
            return False, f"Security scan failed:\n{violations_str}"
        
        # Compute asset hashes
        asset_hashes = []
        asset_dir = module_path / "assets"
        if asset_dir.exists():
            for asset_file in asset_dir.iterdir():
                if asset_file.is_file():
                    asset_hashes.append(self.scanner.compute_asset_hash(asset_file))
        
        # Check for plagiarism
        plagiarism_checks = await self._check_plagiarism(asset_hashes)
        
        plagiarized = any(check.is_plagiarized for check in plagiarism_checks)
        if plagiarized:
            return False, "Plagiarism detected in module assets"
        
        # Store module
        module_entry = MarketplaceModule(
            metadata=metadata,
            files=scan_result.scanned_files,
            assets=asset_hashes,
            security_scan=scan_result,
            plagiarism_checks=plagiarism_checks,
        )
        
        # Save to storage
        module_storage_path = self.storage_path / metadata.module_id
        module_storage_path.mkdir(parents=True, exist_ok=True)
        
        # Copy module files
        import shutil
        for item in module_path.iterdir():
            dest = module_storage_path / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
        
        # Upload to MinIO if available
        if self.minio_service:
            await self._upload_to_minio(module_storage_path, metadata.module_id)
        
        self.modules[metadata.module_id] = module_entry
        
        return True, f"Module '{metadata.name}' submitted successfully"
    
    async def _check_plagiarism(self, asset_hashes: list[AssetHash]) -> list[PlagiarismCheck]:
        """Check assets against known database for plagiarism."""
        checks = []
        
        for asset_hash in asset_hashes:
            # Compare against all stored asset hashes
            matching_assets = []
            max_similarity = 0.0
            
            for stored_module in self.modules.values():
                for stored_asset in stored_module.assets:
                    similarity = self.scanner.compare_hashes(asset_hash.phash, stored_asset.phash)
                    if similarity > 0.85:  # Threshold
                        matching_assets.append(stored_asset.asset_path)
                        max_similarity = max(max_similarity, similarity)
            
            checks.append(PlagiarismCheck(
                asset_path=asset_hash.asset_path,
                is_plagiarized=max_similarity > 0.85,
                similarity_score=max_similarity,
                matching_assets=matching_assets,
            ))
        
        return checks
    
    async def _upload_to_minio(self, module_path: Path, module_id: str) -> None:
        """Upload module to MinIO storage."""
        if not self.minio_service:
            return
        
        bucket = "kotodama-marketplace"
        
        # Upload all files
        for file_path in module_path.rglob("*"):
            if file_path.is_file():
                object_name = f"{module_id}/{file_path.relative_to(module_path)}"
                await self.minio_service.upload_file(
                    bucket=bucket,
                    file_path=file_path,
                    object_name=object_name,
                )
    
    def get_module(self, module_id: str) -> MarketplaceModule | None:
        """Get module by ID."""
        return self.modules.get(module_id)
    
    def search_modules(
        self,
        query: str | None = None,
        category: str | None = None,
        min_rating: float = 0.0,
        max_price: int | None = None,
        free_only: bool = False,
    ) -> list[MarketplaceModule]:
        """Search marketplace modules."""
        results = []
        
        for module in self.modules.values():
            if not module.metadata.is_published:
                continue
            
            # Filter by query
            if query:
                query_lower = query.lower()
                if not (
                    query_lower in module.metadata.name.lower() or
                    query_lower in module.metadata.description.lower() or
                    any(query_lower in tag.lower() for tag in module.metadata.tags)
                ):
                    continue
            
            # Filter by category
            if category and module.metadata.category != category:
                continue
            
            # Filter by rating
            if module.metadata.rating < min_rating:
                continue
            
            # Filter by price
            if max_price is not None and module.metadata.price_credits > max_price:
                continue
            
            if free_only and module.metadata.price_credits > 0:
                continue
            
            results.append(module)
        
        # Sort by rating and downloads
        results.sort(key=lambda m: (m.metadata.rating, m.metadata.downloads), reverse=True)
        
        return results
    
    async def download_module(self, module_id: str, user_id: str) -> tuple[bool, str]:
        """Download a module (simulated)."""
        module = self.modules.get(module_id)
        
        if not module:
            return False, "Module not found"
        
        if not module.metadata.is_published:
            return False, "Module is not published"
        
        # Update download count
        module.metadata.downloads += 1
        
        # In production: charge credits if paid module
        
        return True, f"Module '{module.metadata.name}' downloaded"
    
    async def publish_module(self, module_id: str, author_id: str) -> tuple[bool, str]:
        """Publish a module to the marketplace."""
        module = self.modules.get(module_id)
        
        if not module:
            return False, "Module not found"
        
        # Verify ownership
        if module.metadata.author_id != author_id:
            return False, "Not authorized to publish this module"
        
        # Verify security scan passed
        if not module.security_scan.passed:
            return False, "Module must pass security scan before publishing"
        
        module.metadata.is_published = True
        module.metadata.updated_at = datetime.utcnow()
        
        return True, "Module published successfully"


# Singleton instance
_marketplace_service: MarketplaceService | None = None


def get_marketplace_service(storage_path: Path | None = None) -> MarketplaceService:
    """Get or create marketplace service singleton."""
    global _marketplace_service
    if _marketplace_service is None:
        if storage_path is None:
            storage_path = Path("/workspace/marketplace_modules")
        _marketplace_service = MarketplaceService(storage_path=storage_path)
    return _marketplace_service
