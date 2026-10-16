"""Private mounted-volume storage. URLs are never a file access mechanism."""
from pathlib import Path

from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import FileSystemStorage


class PrivateDocumentStorage(FileSystemStorage):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('file_permissions_mode', 0o600)
        kwargs.setdefault('directory_permissions_mode', 0o700)
        super().__init__(*args, **kwargs)

    def url(self, name):
        raise ValueError('Private files are available only through authorized download views.')

    def path(self, name):
        result = super().path(name)
        root = Path(self.location).resolve()
        if not Path(result).resolve().is_relative_to(root):
            raise SuspiciousFileOperation('Private document path leaves the storage root.')
        return result
