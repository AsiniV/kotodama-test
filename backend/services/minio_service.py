"""
MinIO Service - Handles asset storage and retrieval from MinIO bucket.
"""

import logging
from pathlib import Path
from datetime import datetime
from typing import Optional
from minio import Minio
from minio.error import S3Error
from backend.core.config import get_settings

settings = get_settings()
logger = logging.getLogger("kotodama.services.minio")


class MinIOService:
    """
    Service for interacting with MinIO object storage.
    Manages asset uploads, downloads, and bucket operations.
    
    Lazy initialization: Client is created on first use to avoid connection errors
    when MinIO is not running during development/testing.
    """
    
    def __init__(self):
        self._client = None
        self.assets_bucket = settings.minio_bucket_assets
        self.builds_bucket = settings.minio_bucket_builds
        self._initialized = False
    
    @property
    def client(self) -> Minio:
        """Lazy-load MinIO client on first access."""
        if self._client is None:
            self._client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure
            )
            self._initialize_buckets()
        return self._client
    
    def _ensure_initialized(self) -> bool:
        """Ensure MinIO is available. Returns False if not."""
        try:
            _ = self.client  # Triggers lazy initialization
            return True
        except Exception as e:
            logger.warning(f"MinIO not available: {e}. Asset storage disabled.")
            return False
    
    def _initialize_buckets(self) -> None:
        """Create buckets if they don't exist."""
        try:
            for bucket in [self.assets_bucket, self.builds_bucket]:
                if not self.client.bucket_exists(bucket):
                    self.client.make_bucket(bucket)
                    logger.info(f"Created bucket: {bucket}")
                else:
                    logger.debug(f"Bucket already exists: {bucket}")
        except S3Error as e:
            logger.error(f"Failed to initialize buckets: {e}")
            raise
    
    async def upload_asset(self, file_path: Path, object_name: str, content_type: str = "image/png") -> str:
        """
        Upload an asset file to MinIO.
        
        Args:
            file_path: Path to the local file
            object_name: Object name in bucket (e.g., "assets/player.png")
            content_type: MIME type of the file
            
        Returns:
            URL/path to the uploaded asset, or local path if MinIO unavailable
        """
        if not self._ensure_initialized():
            # Fallback: return local path instead of MinIO URL
            logger.warning(f"MinIO unavailable, using local path for {object_name}")
            return f"file://{file_path}"
        
        try:
            # Upload file to assets bucket
            self.client.fput_object(
                bucket_name=self.assets_bucket,
                object_name=object_name,
                file_path=str(file_path),
                content_type=content_type
            )
            
            logger.info(f"Uploaded asset: {object_name}")
            return f"minio://{self.assets_bucket}/{object_name}"
            
        except S3Error as e:
            logger.error(f"Failed to upload asset {object_name}: {e}")
            # Fallback to local path
            return f"file://{file_path}"
    
    async def download_asset(self, object_name: str, destination_path: Path) -> Path:
        """
        Download an asset from MinIO to local storage.
        
        Args:
            object_name: Object name in bucket
            destination_path: Local path to save the file
            
        Returns:
            Path to the downloaded file, or destination_path if MinIO unavailable
        """
        if not self._ensure_initialized():
            # Fallback: assume file already exists locally
            logger.warning(f"MinIO unavailable, assuming local file for {object_name}")
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            return destination_path
        
        try:
            # Ensure destination directory exists
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Download file
            self.client.fget_object(
                bucket_name=self.assets_bucket,
                object_name=object_name,
                file_path=str(destination_path)
            )
            
            logger.info(f"Downloaded asset: {object_name} -> {destination_path}")
            return destination_path
            
        except S3Error as e:
            logger.error(f"Failed to download asset {object_name}: {e}")
            # Return destination anyway (may already exist)
            return destination_path
    
    async def upload_build(self, file_path: Path, project_id: str, build_type: str = "web") -> str:
        """
        Upload a game build to MinIO.
        
        Args:
            file_path: Path to the build file (ZIP or HTML)
            project_id: Project identifier
            build_type: Type of build ("web", "apk", etc.)
            
        Returns:
            URL/path to the uploaded build
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        object_name = f"builds/{project_id}/{build_type}_{timestamp}.zip"
        
        try:
            self.client.fput_object(
                bucket_name=self.builds_bucket,
                object_name=object_name,
                file_path=str(file_path),
                content_type="application/zip"
            )
            
            logger.info(f"Uploaded build: {object_name}")
            return f"minio://{self.builds_bucket}/{object_name}"
            
        except S3Error as e:
            logger.error(f"Failed to upload build: {e}")
            raise
    
    async def get_presigned_url(self, object_name: str, bucket: Optional[str] = None, expires: int = 3600) -> str:
        """
        Generate a presigned URL for temporary access to an object.
        
        Args:
            object_name: Object name in bucket
            bucket: Bucket name (defaults to assets bucket)
            expires: URL expiration time in seconds
            
        Returns:
            Presigned URL string
        """
        bucket_name = bucket or self.assets_bucket
        
        try:
            url = self.client.presigned_get_object(
                bucket_name=bucket_name,
                object_name=object_name,
                expires=datetime.timedelta(seconds=expires)
            )
            return url
        except S3Error as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            raise
    
    async def list_assets(self, prefix: str = "assets/") -> list[str]:
        """
        List all assets with a given prefix.
        
        Args:
            prefix: Object name prefix to filter by
            
        Returns:
            List of object names
        """
        try:
            objects = self.client.list_objects(
                bucket_name=self.assets_bucket,
                prefix=prefix,
                recursive=True
            )
            return [obj.object_name for obj in objects]
        except S3Error as e:
            logger.error(f"Failed to list assets: {e}")
            raise
    
    async def delete_asset(self, object_name: str) -> bool:
        """
        Delete an asset from MinIO.
        
        Args:
            object_name: Object name to delete
            
        Returns:
            True if successful
        """
        try:
            self.client.remove_object(
                bucket_name=self.assets_bucket,
                object_name=object_name
            )
            logger.info(f"Deleted asset: {object_name}")
            return True
        except S3Error as e:
            logger.error(f"Failed to delete asset {object_name}: {e}")
            return False
    
    async def asset_exists(self, object_name: str) -> bool:
        """
        Check if an asset exists in the bucket.
        
        Args:
            object_name: Object name to check
            
        Returns:
            True if exists
        """
        try:
            self.client.stat_object(
                bucket_name=self.assets_bucket,
                object_name=object_name
            )
            return True
        except S3Error:
            return False


# Singleton instance
_minio_service: Optional[MinIOService] = None


def get_minio_service() -> MinIOService:
    """Get or create MinIO service singleton."""
    global _minio_service
    if _minio_service is None:
        _minio_service = MinIOService()
    return _minio_service
