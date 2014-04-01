# -*- coding: utf-8 -*-
import os
import logging

from framework import make_response

from website.project.utils import get_cache_content
from website.util import rubeus
from website.addons.dropbox.client import get_node_addon_client

logger = logging.getLogger(__name__)
debug = logger.debug


# TODO: Generalize this for other addons?
class DropboxNodeLogger(object):
    """Helper class for adding correctly-formatted Dropbox logs to nodes.

    Usage: ::

        from website.project.model import NodeLog

        file_obj = DropboxFile(path='foo/bar.txt')
        file_obj.save()
        node = ...
        auth = ...
        nodelogger = DropboxNodeLogger(node, auth, file_obj)
        nodelogger.log(NodeLog.FILE_REMOVED, save=True)


    :param Node node: The node to add logs to
    :param Auth auth: Authorization of the person who did the action.
    :param DropboxFile file_obj: File object for file-related logs.
    """
    def __init__(self, node, auth, file_obj=None, path=None):
        self.node = node
        self.auth = auth
        self.file_obj = file_obj
        self.path = path

    def log(self, action, extra=None, save=False):
        """Log an event. Wraps the Node#add_log method, automatically adding
        relevant parameters and prefixing log events with `"dropbox_"`.

        :param str action: Log action. Should be a class constant from NodeLog.
        :param dict extra: Extra parameters to add to the ``params`` dict of the
            new NodeLog.
        """
        params = {
            'project': self.node.parent_id,
            'node': self.node._primary_key,
            'folder': self.node.get_addon('dropbox').folder
        }
        # If logging a file-related action, add the file's view and download URLs
        if self.file_obj or self.path:
            path = self.file_obj.path if self.file_obj else self.path
            cleaned_path = clean_path(path)
            params.update({
                'urls': {
                    'view': self.node.web_url_for('dropbox_view_file', path=cleaned_path),
                    'download': self.node.web_url_for(
                        'dropbox_download', path=cleaned_path)
                },
                'path': cleaned_path,
            })
        if extra:
            params.update(extra)
        # Prefix the action with dropbox_
        self.node.add_log(
            action="dropbox_{0}".format(action),
            params=params,
            auth=self.auth
        )
        if save:
            self.node.save()


def get_file_name(path):
    """Given a path, get just the base filename.
    Handles "/foo/bar/baz.txt/" -> "baz.txt"
    """
    return os.path.basename(path.strip('/'))


def clean_path(path):
    """Ensure a path is formatted correctly for url_for."""
    if path is None:
        return ''
    return path.strip('/')


def make_file_response(fileobject, metadata):
    """Builds a response from a file-like object and metadata returned by
    a Dropbox client.
    """
    resp = make_response(fileobject.read())
    disposition = 'attachment; filename={0}'.format(metadata['path'])
    resp.headers['Content-Disposition'] = disposition
    resp.headers['Content-Type'] = metadata.get('mime_type', 'application/octet-stream')
    return resp


def render_dropbox_file(file_obj, client=None, rev=None):
    """Render a DropboxFile with the MFR.

    :param DropboxFile file_obj: The file's GUID record.
    :param DropboxClient client:
    :param str rev: Revision ID.
    :return: The HTML for the rendered file.
    """
    # Filename for the cached MFR HTML file
    cache_name = file_obj.get_cache_filename(client=client, rev=rev)
    node_settings = file_obj.node.get_addon('dropbox')
    rendered = get_cache_content(node_settings, cache_name)
    if rendered is None:  # not in MFR cache
        dropbox_client = client or get_node_addon_client(node_settings)
        file_response, metadata = dropbox_client.get_file_and_metadata(
            file_obj.path, rev=rev)
        rendered = get_cache_content(
            node_settings=node_settings,
            cache_file=cache_name,
            start_render=True,
            file_path=get_file_name(file_obj.path),
            file_content=file_response.read(),
            download_path=file_obj.download_url
        )
    return rendered


def ensure_leading_slash(path):
    if not path.startswith('/'):
        return '/' + path
    return path


def build_dropbox_urls(item, node):
    path = clean_path(item['path'])  # Strip trailing and leading slashes
    if item['is_dir']:
        return {
            'upload': node.api_url_for('dropbox_upload', path=path),
            # Endpoint for fetching all of a folder's contents
            'fetch':  node.api_url_for('dropbox_hgrid_data_contents', path=path),
            # Add extra endpoint for fetching folders only (used by node settings page)
            # NOTE: querystring params in camel-case
            'folders': node.api_url_for('dropbox_hgrid_data_contents',
                path=path, foldersOnly=1)
        }
    else:
        return {
            'download': node.web_url_for('dropbox_download', path=path),
            'view': node.web_url_for('dropbox_view_file', path=path),
            'delete': node.api_url_for('dropbox_delete_file', path=path)
        }


def metadata_to_hgrid(item, node, permissions):
    """Serializes a dictionary of metadata (returned from the DropboxClient)
    to the format expected by Rubeus/HGrid.
    """
    filename = get_file_name(item['path'])
    serialized = {
        'addon': 'dropbox',
        'permissions': permissions,
        'name': get_file_name(item['path']),
        'ext': os.path.splitext(filename)[1],
        rubeus.KIND: rubeus.FOLDER if item['is_dir'] else rubeus.FILE,
        'urls': build_dropbox_urls(item, node),
        'path': item['path'],
    }
    return serialized


def get_share_folder_uri(path):
    """Return the URI for sharing a folder through the dropbox interface.
    This is not exposed through Dropbox's REST API, so need to build the URI
    "manually".
    """
    cleaned = clean_path(path)
    return ('https://dropbox.com/home/{cleaned}'
            '?shareoptions=1&share_subfolder=0&share=1').format(cleaned=cleaned)
