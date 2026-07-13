import logging

from django.db import connection
from django.http import JsonResponse
from django.views import View

from books.storage import _get_s3_client

logger = logging.getLogger(__name__)


class HealthCheckView(View):
    """Industry-standard health check endpoint.

    Checks:
    1. Database connectivity (executes a simple query).
    2. S3 Object Storage connectivity (checks bucket accessibility).
    """

    def get(self, request):
        status_data = {
            'status': 'healthy',
            'checks': {
                'database': 'unknown',
                'storage': 'unknown',
            },
        }
        status_code = 200

        # 1. Check Database connection
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1;')
                row = cursor.fetchone()
                if row and row[0] == 1:
                    status_data['checks']['database'] = 'healthy'
                else:
                    status_data['checks']['database'] = 'unhealthy'
                    status_data['status'] = 'unhealthy'
                    status_code = 503
        except Exception as e:
            logger.error('Health check failed - Database error: %s', e)
            status_data['checks']['database'] = 'failed'
            status_data['status'] = 'unhealthy'
            status_code = 503

        # 2. Check S3 Storage accessibility
        try:
            s3_client = _get_s3_client()
            from django.conf import settings
            if settings.S3_BUCKET_NAME:
                # Run a head_bucket check to ensure bucket exists and credentials are valid
                s3_client.head_bucket(Bucket=settings.S3_BUCKET_NAME)
                status_data['checks']['storage'] = 'healthy'
            else:
                status_data['checks']['storage'] = 'not_configured'
        except Exception as e:
            logger.error('Health check failed - Storage error: %s', e)
            status_data['checks']['storage'] = 'failed'
            status_data['status'] = 'unhealthy'
            status_code = 503

        return JsonResponse(status_data, status=status_code)
