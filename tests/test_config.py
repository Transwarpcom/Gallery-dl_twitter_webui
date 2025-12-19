import unittest
import os
from app import create_app

class TestConfig(unittest.TestCase):
    def test_secret_key_is_set(self):
        """Test that the application has a SECRET_KEY set."""
        app = create_app()
        self.assertTrue(app.config.get('SECRET_KEY'), "SECRET_KEY is not set in the configuration!")

    def test_secret_key_override(self):
        """Test that SECRET_KEY can be overridden by environment variable."""
        os.environ['SECRET_KEY'] = 'new-secure-key'
        # We need to reload the app or config to pick up the env var change
        # But config.py is read at module level, so we might need to reload the module or just trust that `create_app` reads it.
        # `create_app` reads `config.py` using `app.config.from_pyfile(config_path)`.
        # Python's import system caches modules. `config.py` is imported as a module in my overwrite, but `from_pyfile` executes it.
        # However, `config.py` uses `os.environ.get` at the top level.

        # Let's try to reload the config module logic by creating a new app.
        # Since `create_app` calls `app.config.from_pyfile`, it re-executes the file.
        app = create_app()
        self.assertEqual(app.config.get('SECRET_KEY'), 'new-secure-key')
        del os.environ['SECRET_KEY']

if __name__ == '__main__':
    unittest.main()
