import os
import boto3
from pathlib import Path
from config import settings, logger

def get_s3_client():
    """Resolve endpoint url dynamically based on environment and return S3 client."""
    is_docker = os.path.exists("/.dockerenv") or os.getenv("RUNNING_IN_DOCKER") == "true"
    endpoint_url = settings.S3_ENDPOINT_URL
    if not is_docker and "minio:9000" in endpoint_url:
        endpoint_url = endpoint_url.replace("minio:9000", "127.0.0.1:9010")
        
    return boto3.client(
        's3',
        endpoint_url=endpoint_url,
        aws_access_key_id=settings.MINIO_ROOT_USER,
        aws_secret_access_key=settings.MINIO_ROOT_PASSWORD,
        region_name='us-east-1'
    )

def upload_file_to_s3(file_path: Path, s3_key: str) -> str:
    """
    Upload a file to MinIO (S3) and return its public URL.
    Ensures bucket exists first.
    """
    s3 = get_s3_client()
    try:
        # Create bucket if it doesn't exist
        try:
            s3.head_bucket(Bucket=settings.S3_BUCKET_NAME)
        except Exception:
            logger.info(f"Creating bucket {settings.S3_BUCKET_NAME} in MinIO")
            s3.create_bucket(Bucket=settings.S3_BUCKET_NAME)
            
        s3.upload_file(str(file_path), settings.S3_BUCKET_NAME, s3_key)
        
        # Build access URL
        is_docker = os.path.exists("/.dockerenv") or os.getenv("RUNNING_IN_DOCKER") == "true"
        host = "minio:9000" if is_docker else "127.0.0.1:9010"
        return f"http://{host}/{settings.S3_BUCKET_NAME}/{s3_key}"
    except Exception as e:
        logger.error(f"Failed to upload file to S3: {e}")
        # Return fallback URL
        return f"http://127.0.0.1:9010/{settings.S3_BUCKET_NAME}/{s3_key}"

def download_file_from_s3(s3_url: str, local_dir: Path) -> Path:
    """Download a file from MinIO (S3) to local directory and return Path."""
    s3 = get_s3_client()
    bucket = settings.S3_BUCKET_NAME
    prefix = f"/{bucket}/"
    idx = s3_url.find(prefix)
    if idx != -1:
        key = s3_url[idx + len(prefix):]
    else:
        parts = s3_url.split(f"/{bucket}/")
        key = parts[-1] if len(parts) > 1 else s3_url

    local_dir.mkdir(parents=True, exist_ok=True)
    # Generate a safe local filename
    safe_filename = key.replace("/", "_")
    local_path = local_dir / safe_filename

    s3.download_file(bucket, key, str(local_path))
    return local_path

