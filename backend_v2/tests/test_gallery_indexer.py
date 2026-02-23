
import unittest
from unittest.mock import MagicMock, patch
import os
import sys

# Add backend_v2 to sys.path if not present, to ensure imports work
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.gallery_indexer import GalleryIndexer

class TestGalleryIndexer(unittest.TestCase):
    def setUp(self):
        # Reset the singleton instance before each test
        GalleryIndexer._instance = None
        self.indexer = GalleryIndexer(output_dir="/tmp/output")

    @patch('services.gallery_indexer.os.path.relpath')
    @patch('services.gallery_indexer.os.path.isfile')
    @patch('services.gallery_indexer.os.stat')
    @patch('services.gallery_indexer.os.path.basename')
    @patch('services.gallery_indexer.os.path.getmtime')
    @patch('infrastructure.image_processor.read_image_metadata')
    def test_process_file_metadata_error(self, mock_read_metadata, mock_getmtime, mock_basename, mock_stat, mock_isfile, mock_relpath):
        # Setup mocks
        mock_relpath.return_value = "image.png"
        mock_isfile.return_value = True

        mock_stat_obj = MagicMock()
        mock_stat_obj.st_size = 1024
        mock_stat_obj.st_mtime = 1600000000
        mock_stat.return_value = mock_stat_obj

        mock_basename.return_value = "image.png"
        mock_getmtime.return_value = 1600000000

        # Simulate exception in read_image_metadata
        mock_read_metadata.side_effect = Exception("Corrupt file")

        # Execute
        result = self.indexer._process_file("/tmp/output/image.png")

        # Assertions
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], "image.png")
        self.assertEqual(result['metadata'], {})
        self.assertNotIn('blurhash', result)

        # Verify read_image_metadata was called
        mock_read_metadata.assert_called_once_with("/tmp/output/image.png")

    @patch('services.gallery_indexer.os.path.relpath')
    @patch('services.gallery_indexer.os.path.isfile')
    @patch('services.gallery_indexer.os.stat')
    @patch('services.gallery_indexer.os.path.basename')
    @patch('services.gallery_indexer.os.path.getmtime')
    @patch('infrastructure.image_processor.read_image_metadata')
    def test_process_file_success(self, mock_read_metadata, mock_getmtime, mock_basename, mock_stat, mock_isfile, mock_relpath):
        # Setup mocks
        mock_relpath.return_value = "image.png"
        mock_isfile.return_value = True

        mock_stat_obj = MagicMock()
        mock_stat_obj.st_size = 1024
        mock_stat_obj.st_mtime = 1600000000
        mock_stat.return_value = mock_stat_obj

        mock_basename.return_value = "image.png"
        mock_getmtime.return_value = 1600000000

        # Simulate successful metadata read
        mock_read_metadata.return_value = {'blurhash': 'hash123', 'foo': 'bar'}

        # Execute
        result = self.indexer._process_file("/tmp/output/image.png")

        # Assertions
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], "image.png")
        self.assertEqual(result['metadata'], {'blurhash': 'hash123', 'foo': 'bar'})
        self.assertEqual(result['blurhash'], 'hash123')

        # Verify read_image_metadata was called
        mock_read_metadata.assert_called_once_with("/tmp/output/image.png")

if __name__ == '__main__':
    unittest.main()
