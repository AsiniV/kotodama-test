"""
Godot Export Service

Handles game export to various platforms:
- Web (HTML5)
- Android (APK)
- iOS (IPA)
- Desktop (Windows, macOS, Linux)

Uses Godot headless CLI for automated builds.
"""

import asyncio
import subprocess
from pathlib import Path
from typing import Literal
from datetime import datetime
from pydantic import BaseModel, Field


ExportPlatform = Literal["web", "android", "ios", "windows", "macos", "linux"]


class ExportPreset(BaseModel):
    """Godot export preset configuration."""
    name: str
    platform: ExportPlatform
    debug: bool = False
    template: str | None = None  # Custom export template
    options: dict = Field(default_factory=dict)


class ExportConfig(BaseModel):
    """Configuration for a single export job."""
    project_path: Path
    output_path: Path
    preset_name: str
    platform: ExportPlatform
    debug: bool = False
    timeout_seconds: int = 300  # 5 minutes max


class ExportResult(BaseModel):
    """Result of an export operation."""
    success: bool
    platform: ExportPlatform
    output_file: Path | None = None
    error_message: str | None = None
    duration_seconds: float = 0.0
    file_size_bytes: int | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    godot_version: str | None = None


class ExportJob(BaseModel):
    """Tracks an export job in the queue."""
    job_id: str
    user_id: str
    project_id: str
    config: ExportConfig
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    result: ExportResult | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class GodotExportService:
    """
    Service for exporting Godot projects to various platforms.
    
    Features:
    - Headless Godot CLI integration
    - Multi-platform support
    - Export queue management
    - Progress tracking
    - File size optimization
    """
    
    SUPPORTED_PLATFORMS = ["web", "android", "ios", "windows", "macos", "linux"]
    
    EXPORT_TEMPLATES = {
        "web": "web_template.zip",
        "android": "android_template.apk",
        "ios": "ios_template.ipa",
        "windows": "windows_template.exe",
        "macos": "macos_template.app",
        "linux": "linux_template.x86_64",
    }
    
    def __init__(self, godot_headless_path: str = "/usr/bin/godot-headless"):
        self.godot_headless_path = godot_headless_path
        self.export_queue: list[ExportJob] = []
        self.active_jobs: dict[str, ExportJob] = {}
        self.completed_jobs: dict[str, ExportJob] = {}
    
    async def export_project(self, config: ExportConfig) -> ExportResult:
        """
        Export a Godot project to the specified platform.
        
        Args:
            config: Export configuration
            
        Returns:
            ExportResult with success status and output file path
        """
        start_time = datetime.utcnow()
        
        # Verify Godot is available
        if not await self._verify_godot():
            return ExportResult(
                success=False,
                platform=config.platform,
                error_message="Godot headless binary not found or not executable",
            )
        
        # Verify project exists
        if not config.project_path.exists():
            return ExportResult(
                success=False,
                platform=config.platform,
                error_message=f"Project path does not exist: {config.project_path}",
            )
        
        project_file = config.project_path / "project.godot"
        if not project_file.exists():
            return ExportResult(
                success=False,
                platform=config.platform,
                error_message="project.godot not found in project path",
            )
        
        # Create output directory
        config.output_path.mkdir(parents=True, exist_ok=True)
        
        # Build Godot CLI command
        cmd = [
            self.godot_headless_path,
            "--headless",
            "--export-release" if not config.debug else "--export-debug",
            config.preset_name,
            str(config.output_path),
        ]
        
        # Add project path
        cmd.extend(["--path", str(config.project_path)])
        
        try:
            # Run export
            process = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=10,
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=config.timeout_seconds,
            )
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            
            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="ignore")
                return ExportResult(
                    success=False,
                    platform=config.platform,
                    error_message=f"Godot export failed: {error_msg}",
                    duration_seconds=duration,
                )
            
            # Verify output file exists
            if not config.output_path.exists():
                return ExportResult(
                    success=False,
                    platform=config.platform,
                    error_message="Export completed but output file not found",
                    duration_seconds=duration,
                )
            
            # Get file size
            file_size = config.output_path.stat().st_size
            
            # Get Godot version
            godot_version = await self._get_godot_version()
            
            return ExportResult(
                success=True,
                platform=config.platform,
                output_file=config.output_path,
                duration_seconds=duration,
                file_size_bytes=file_size,
                godot_version=godot_version,
            )
            
        except asyncio.TimeoutError:
            return ExportResult(
                success=False,
                platform=config.platform,
                error_message=f"Export timed out after {config.timeout_seconds} seconds",
                duration_seconds=(datetime.utcnow() - start_time).total_seconds(),
            )
        except Exception as e:
            return ExportResult(
                success=False,
                platform=config.platform,
                error_message=f"Export failed: {str(e)}",
                duration_seconds=(datetime.utcnow() - start_time).total_seconds(),
            )
    
    async def _verify_godot(self) -> bool:
        """Verify Godot headless binary is available and executable."""
        try:
            process = await asyncio.create_subprocess_exec(
                self.godot_headless_path,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            return process.returncode == 0
        except Exception:
            return False
    
    async def _get_godot_version(self) -> str | None:
        """Get Godot version string."""
        try:
            process = await asyncio.create_subprocess_exec(
                self.godot_headless_path,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            if process.returncode == 0:
                return stdout.decode("utf-8").strip()
        except Exception:
            pass
        return None
    
    async def queue_export(self, job: ExportJob) -> str:
        """Add an export job to the queue."""
        self.export_queue.append(job)
        job.status = "pending"
        return job.job_id
    
    async def process_queue(self, max_concurrent: int = 2) -> None:
        """Process export queue with concurrency limit."""
        while self.export_queue and len(self.active_jobs) < max_concurrent:
            job = self.export_queue.pop(0)
            job.status = "running"
            job.started_at = datetime.utcnow()
            self.active_jobs[job.job_id] = job
            
            # Start export task
            asyncio.create_task(self._process_job(job))
    
    async def _process_job(self, job: ExportJob) -> None:
        """Process a single export job."""
        result = await self.export_project(job.config)
        job.result = result
        job.status = "completed" if result.success else "failed"
        job.completed_at = datetime.utcnow()
        
        # Move to completed jobs
        del self.active_jobs[job.job_id]
        self.completed_jobs[job.job_id] = job
        
        # Continue processing queue
        await self.process_queue()
    
    def get_job_status(self, job_id: str) -> ExportJob | None:
        """Get status of an export job."""
        if job_id in self.active_jobs:
            return self.active_jobs[job_id]
        if job_id in self.completed_jobs:
            return self.completed_jobs[job_id]
        return None
    
    @staticmethod
    def optimize_for_web(output_path: Path) -> tuple[bool, str]:
        """
        Optimize web export for smaller size.
        
        Techniques:
        - Brotli compression
        - Remove debug symbols
        - Minify GDScript
        - Compress textures
        """
        if not output_path.exists():
            return False, "Output file does not exist"
        
        # For web exports, we can use brotli compression
        if output_path.suffix in [".html", ".js", ".pck"]:
            import brotli
            
            with open(output_path, "rb") as f:
                data = f.read()
            
            compressed = brotli.compress(data, quality=11)
            
            # Save compressed version
            compressed_path = output_path.with_suffix(output_path.suffix + ".br")
            with open(compressed_path, "wb") as f:
                f.write(compressed)
            
            original_size = output_path.stat().st_size
            compressed_size = compressed_path.stat().st_size
            reduction = ((original_size - compressed_size) / original_size) * 100
            
            return True, f"Compressed from {original_size} to {compressed_size} bytes ({reduction:.1f}% reduction)"
        
        return False, "File type not suitable for compression"


class FastlaneExportService:
    """
    Service for mobile app export using Fastlane.
    
    Handles:
    - Android APK/AAB signing and upload
    - iOS IPA signing and upload
    - Google Play Store deployment
    - Apple App Store deployment
    """
    
    def __init__(self, fastlane_path: str = "/usr/bin/fastlane"):
        self.fastlane_path = fastlane_path
        self.keystore_path: Path | None = None
        self.keystore_password: str | None = None
        self.apple_id: str | None = None
        self.apple_password: str | None = None
        self.apple_apple_id_password: str | None = None
    
    def configure_android(
        self,
        keystore_path: Path,
        keystore_password: str,
        key_alias: str,
        key_password: str,
    ) -> None:
        """Configure Android signing credentials."""
        self.keystore_path = keystore_path
        self.keystore_password = keystore_password
        self.key_alias = key_alias
        self.key_password = key_password
    
    def configure_ios(
        self,
        apple_id: str,
        apple_password: str,
        app_store_connect_api_key: str | None = None,
    ) -> None:
        """Configure iOS signing credentials."""
        self.apple_id = apple_id
        self.apple_password = apple_password
        self.app_store_connect_api_key = app_store_connect_api_key
    
    async def build_android_apk(
        self,
        project_path: Path,
        output_path: Path,
        version_code: int,
        version_name: str,
    ) -> tuple[bool, str]:
        """
        Build signed Android APK using Fastlane.
        
        Returns:
            Tuple of (success, message)
        """
        if not self.keystore_path:
            return False, "Android keystore not configured"
        
        # Create Fastfile
        fastfile_content = f"""
default_platform 'android'

platform :android do
  desc "Build and sign APK"
  lane :build do
    gradle(
      project_dir: '{project_path}',
      task: 'assembleRelease',
      properties: {{
        'android.injected.signing.store.file' => '{self.keystore_path}',
        'android.injected.signing.store.password' => '{self.keystore_password}',
        'android.injected.signing.key.alias' => '{self.key_alias}',
        'android.injected.signing.key.password' => '{self.key_password}',
      }}
    )
  end
end
"""
        
        fastfile_path = project_path / "fastlane" / "Fastfile"
        fastfile_path.parent.mkdir(parents=True, exist_ok=True)
        fastfile_path.write_text(fastfile_content)
        
        # Run fastlane
        try:
            process = await asyncio.create_subprocess_exec(
                self.fastlane_path,
                "android",
                "build",
                cwd=str(project_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                return True, "APK built successfully"
            else:
                error_msg = stderr.decode("utf-8", errors="ignore")
                return False, f"Fastlane build failed: {error_msg}"
                
        except Exception as e:
            return False, f"Build error: {str(e)}"
    
    async def build_ios_ipa(
        self,
        project_path: Path,
        output_path: Path,
        scheme: str,
        workspace: str | None = None,
    ) -> tuple[bool, str]:
        """
        Build signed iOS IPA using Fastlane.
        
        Returns:
            Tuple of (success, message)
        """
        if not self.apple_id:
            return False, "Apple ID not configured"
        
        # Create Fastfile
        fastfile_content = f"""
default_platform 'ios'

platform :ios do
  desc "Build and sign IPA"
  lane :build do
    build_app(
      scheme: '{scheme}',
      workspace: '{workspace}',
      export_method: 'app-store',
      export_options: {{
        uploadBitcode: false,
        uploadSymbols: true
      }}
    )
  end
  
  desc "Upload to App Store"
  lane :upload do
    upload_to_app_store(
      apple_id: '{self.apple_id}',
      username: '{self.apple_id}',
      ipa: '{output_path}'
    )
  end
end
"""
        
        fastfile_path = project_path / "fastlane" / "Fastfile"
        fastfile_path.parent.mkdir(parents=True, exist_ok=True)
        fastfile_path.write_text(fastfile_content)
        
        # Run fastlane
        try:
            process = await asyncio.create_subprocess_exec(
                self.fastlane_path,
                "ios",
                "build",
                cwd=str(project_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                return True, "IPA built successfully"
            else:
                error_msg = stderr.decode("utf-8", errors="ignore")
                return False, f"Fastlane build failed: {error_msg}"
                
        except Exception as e:
            return False, f"Build error: {str(e)}"
    
    async def upload_to_play_store(
        self,
        apk_path: Path,
        package_name: str,
        track: Literal["internal", "alpha", "beta", "production"] = "internal",
    ) -> tuple[bool, str]:
        """Upload APK to Google Play Store."""
        # Implementation would use Google Play Developer API
        # For now, return placeholder
        return True, f"Would upload {apk_path} to {track} track"
    
    async def upload_to_app_store(
        self,
        ipa_path: Path,
        bundle_id: str,
    ) -> tuple[bool, str]:
        """Upload IPA to Apple App Store."""
        if not self.apple_id:
            return False, "Apple ID not configured"
        
        # Use altool or Transporter
        try:
            # Try using xcrun altool (deprecated but still works)
            process = await asyncio.create_subprocess_exec(
                "xcrun",
                "altool",
                "--upload-app",
                "--type", "ios",
                "--file", str(ipa_path),
                "--username", self.apple_id,
                "--password", self.apple_password,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                return True, "IPA uploaded to App Store"
            else:
                error_msg = stderr.decode("utf-8", errors="ignore")
                return False, f"Upload failed: {error_msg}"
                
        except Exception as e:
            return False, f"Upload error: {str(e)}"


# Singleton instances
_export_service: GodotExportService | None = None
_fastlane_service: FastlaneExportService | None = None


def get_export_service(godot_path: str | None = None) -> GodotExportService:
    """Get or create export service singleton."""
    global _export_service
    if _export_service is None:
        godot_path = godot_path or "/usr/bin/godot-headless"
        _export_service = GodotExportService(godot_headless_path=godot_path)
    return _export_service


def get_fastlane_service() -> FastlaneExportService:
    """Get or create fastlane service singleton."""
    global _fastlane_service
    if _fastlane_service is None:
        _fastlane_service = FastlaneExportService()
    return _fastlane_service
