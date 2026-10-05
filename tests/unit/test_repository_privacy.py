"""Publication checks must catch private data deleted from the current tree."""
import subprocess

from scripts.check_repository import check_history, privacy_findings


def test_credential_sentinel_is_only_exempt_in_tests():
    sentinel = 'ghp_' + 'x' * 24
    assert privacy_findings('tests/unit/example.py', sentinel) == []
    assert privacy_findings('docs/example.md', sentinel) == ['credential-shaped content']


def test_history_finds_deleted_private_file_and_old_author(tmp_path):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=tmp_path, text=True)

    git('init', '--quiet')
    git('config', 'user.name', 'Fixture Contributor')
    git('config', 'user.email', 'fixture@example.org')
    git('config', 'commit.gpgsign', 'false')
    private = tmp_path / 'old.md'
    private.write_text('/' + 'Users' + '/fixture/private-project\n')
    git('add', 'old.md')
    author_email = 'fixture@' + 'gmail.com'
    git('-c', 'user.email=' + author_email, 'commit', '--quiet', '-m', 'Old record')
    private.unlink()
    git('add', '-u')
    git('commit', '--quiet', '-m', 'Remove old record')
    report = check_history(tmp_path)
    assert report['blobs'] == 1
    assert any('old.md: personal machine path' in error for error in report['errors'])
    assert 'history: 1 personal email(s) in commit identities' in report['errors']
    assert all(author_email not in error for error in report['errors'])
    assert all('private-project' not in error for error in report['errors'])


def test_history_accepts_clean_repository(tmp_path):
    def git(*args):
        subprocess.check_call(['git', *args], cwd=tmp_path)

    git('init', '--quiet')
    (tmp_path / 'README.md').write_text('Public project description.\n')
    git('add', 'README.md')
    git('-c', 'user.name=Fixture Contributor', '-c', 'user.email=fixture@example.org',
        '-c', 'commit.gpgsign=false', 'commit', '--quiet', '-m', 'Initial public tree')
    assert check_history(tmp_path) == {'blobs': 1, 'errors': []}
