"""S3-compatible object storage client for cached book content.

Works with AWS S3, Heroku Bucketeer, and DigitalOcean Spaces — all use the
same S3 API. Reads credentials from Django settings (which in turn read from
Heroku config vars).
"""

import logging

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from django.conf import settings

logger = logging.getLogger(__name__)


def _get_s3_client():
    """Create a boto3 S3 client from Django settings."""
    kwargs = {
        'aws_access_key_id': settings.S3_ACCESS_KEY_ID,
        'aws_secret_access_key': settings.S3_SECRET_ACCESS_KEY,
        'region_name': settings.S3_REGION,
        'config': Config(
            signature_version='s3v4',
            retries={'max_attempts': 3, 'mode': 'standard'},
        ),
    }
    if settings.S3_ENDPOINT_URL:
        kwargs['endpoint_url'] = settings.S3_ENDPOINT_URL
    return boto3.client('s3', **kwargs)


def upload_file_to_s3(file_bytes, key, content_type='application/octet-stream'):
    """Upload bytes to S3 and return the public URL.

    Args:
        file_bytes: The file content as bytes.
        key: The S3 object key (e.g. 'books/84/pg84.epub').
        content_type: MIME type for the Content-Type header.

    Returns:
        str: The public URL of the uploaded object.

    Raises:
        ClientError: If the upload fails.
    """
    client = _get_s3_client()
    bucket = settings.S3_BUCKET_NAME

    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=file_bytes,
        ContentType=content_type,
    )

    # Build the public URL
    if settings.S3_CUSTOM_DOMAIN:
        url = f'{settings.S3_CUSTOM_DOMAIN.rstrip("/")}/{key}'
    elif settings.S3_ENDPOINT_URL:
        url = f'{settings.S3_ENDPOINT_URL.rstrip("/")}/{bucket}/{key}'
    else:
        url = f'https://{bucket}.s3.amazonaws.com/{key}'

    logger.info('Uploaded %s (%d bytes) to %s', key, len(file_bytes), url)
    return url


def check_file_exists(key):
    """Check if a file already exists in S3.

    Returns:
        bool: True if the object exists.
    """
    client = _get_s3_client()
    try:
        client.head_object(Bucket=settings.S3_BUCKET_NAME, Key=key)
        return True
    except ClientError:
        return False


def delete_file_from_s3(key):
    """Delete a file from S3.

    Args:
        key: The S3 object key to delete.
    """
    client = _get_s3_client()
    client.delete_object(Bucket=settings.S3_BUCKET_NAME, Key=key)
    logger.info('Deleted %s from S3', key)


def get_presigned_download_url(key, expires_in=3600):
    """Generate a secure presigned URL to share an S3 object.

    Allows clients to download the cached book securely without requiring
    public read bucket permissions.

    Args:
        key: The S3 object key.
        expires_in: Time in seconds for the link to remain valid (default: 1 hr).

    Returns:
        str: Presigned URL string.
    """
    client = _get_s3_client()
    try:
        url = client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': settings.S3_BUCKET_NAME,
                'Key': key
            },
            ExpiresIn=expires_in
        )
        return url
    except Exception as e:
        logger.error('Failed to generate presigned URL for %s: %s', key, e)
        # Fallback to direct URL if presigned URL generation fails
        if settings.S3_ENDPOINT_URL:
            return f'{settings.S3_ENDPOINT_URL.rstrip("/")}/{settings.S3_BUCKET_NAME}/{key}'
        return f'https://{settings.S3_BUCKET_NAME}.s3.amazonaws.com/{key}'

