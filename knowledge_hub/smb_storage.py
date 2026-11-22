"""Direct SMB test storage. Credentials are read from HA's private options file."""
import ntpath
import os
import re
import stat


class Conflict(Exception):
    pass


def safe_parts(path):
    if not isinstance(path, str) or not path:
        raise ValueError('Invalid SMB path')
    parts = path.split('/')
    if any(not re.fullmatch(r'[^\\/:*?"<>|\x00-\x1f]+', p) or p.startswith('.') or p.endswith((' ', '.')) for p in parts):
        raise ValueError('Invalid SMB path')
    return parts


class SMBStorage:
    def __init__(self, options, client=None):
        if client is None:
            import smbclient as client
        self.client = client
        self.client.ClientConfig(skip_dfs=True)
        self.server = options['smb_server']
        self.share = options['smb_share']
        if not re.fullmatch(r'[A-Za-z0-9.-]+', self.server) or not re.fullmatch(r'[A-Za-z0-9_. -]+', self.share) or self.share.startswith('.'):
            raise ValueError('Invalid SMB server or share')
        self.base = '\\\\' + self.server + '\\' + self.share
        self.prefix = safe_parts(options['smb_subdirectory']) if options.get('smb_subdirectory') else []
        self.kwargs = {'username': options['smb_username'], 'password': options['smb_password'],
                       'connection_timeout': 10, 'auth_protocol': 'ntlm', 'require_signing': True}

    def list_files(self):
        """List regular files without following SMB reparse points."""
        files = []
        def walk(path, relative):
            with self.client.scandir(path, **self.kwargs) as entries:
                for entry in entries:
                    name = entry.name
                    try:
                        safe_parts(name)
                    except ValueError:
                        continue
                    rel = relative + '/' + name if relative else name
                    info = entry.stat(follow_symlinks=False)
                    if info.st_file_attributes & 0x400 or stat.S_ISLNK(info.st_mode):
                        continue
                    if stat.S_ISDIR(info.st_mode):
                        walk(ntpath.join(path, name), rel)
                    elif stat.S_ISREG(info.st_mode):
                        files.append(rel)
                        if len(files) > 5000:
                            raise OSError('Too many files')
        try:
            current = self.base
            for part in self.prefix:
                current = ntpath.join(current, part)
                info = self.client.lstat(current, **self.kwargs)
                if info.st_file_attributes & 0x400 or not stat.S_ISDIR(info.st_mode):
                    raise OSError('Unsafe SMB directory')
            walk(current, '')
            return files
        except OSError:
            raise
        except Exception as exc:
            raise OSError('SMB listing failed') from exc

    def _target(self, name):
        parts = self.prefix + safe_parts(name)
        current = self.base
        for i, part in enumerate(parts):
            current = ntpath.join(current, part)
            info = self.client.lstat(current, **self.kwargs)
            if info.st_file_attributes & 0x400 or stat.S_ISLNK(info.st_mode):
                raise OSError('SMB reparse points are not permitted')
            if i < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
                raise OSError('SMB directory is unavailable')
            if i == len(parts) - 1 and not stat.S_ISREG(info.st_mode):
                raise OSError('SMB file is unavailable')
        return current

    def read(self, name):
        try:
            target = self._target(name)
            with self.client.open_file(target, mode='rb', **self.kwargs) as file:
                return file.read()
        except (OSError, ValueError):
            raise
        except Exception as exc:
            raise OSError('SMB read failed') from exc

    def write(self, name, content, revision, digest):
        tmp = None
        try:
            target = self._target(name)
            if digest(self.read(name)) != revision:
                raise Conflict()
            tmp = ntpath.join(ntpath.dirname(target), '.kh-' + os.urandom(12).hex())
            with self.client.open_file(tmp, mode='xb', **self.kwargs) as file:
                file.write(content)
            if digest(self.read(name)) != revision:
                raise Conflict()
            self._target(name)
            self._replace(tmp, target)
            tmp = None
        except (Conflict, OSError, ValueError):
            raise
        except Exception as exc:
            raise OSError('SMB write failed') from exc
        finally:
            if tmp:
                try:
                    self.client.remove(tmp, **self.kwargs)
                except Exception:
                    pass

    def _replace(self, source, target):
        # smbclient.replace opens the destination with FILE_EXECUTE, which
        # Samba can reject for ordinary non-executable Markdown files. Both
        # paths here are already constructed under one fixed SMB share.
        from smbclient._io import SMBRawIO, SMBFileTransaction, set_info
        from smbprotocol.file_info import FileRenameInformation
        from smbprotocol.open import CreateOptions, FilePipePrinterAccessMask
        with SMBRawIO(source, mode='r', share_access='rwd',
                      desired_access=FilePipePrinterAccessMask.DELETE,
                      create_options=CreateOptions.FILE_OPEN_REPARSE_POINT,
                      **self.kwargs) as raw:
            with SMBFileTransaction(raw) as transaction:
                rename = FileRenameInformation()
                rename['replace_if_exists'] = True
                rename['file_name'] = ntpath.relpath(target, self.base)
                set_info(transaction, rename)
