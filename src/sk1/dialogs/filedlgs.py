# -*- coding: utf-8 -*-
#
#  Copyright (C) 2013 by Igor E. Novikov
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import wx

import wal
from sk1 import _
from uc2 import uc2const
from uc2.utils.fs import path_system


def _get_open_filters(items=None):
    items = items or []
    wildcard = ''
    descr = uc2const.FORMAT_DESCRIPTION
    ext = uc2const.FORMAT_EXTENSION
    if not items:
        items = [] + uc2const.LOADER_FORMATS
    wildcard += _('All supported formats') + '|'
    for item in items:
        for extension in ext[item]:
            wildcard += '*.' + extension + ';'
            wildcard += '*.' + extension.upper() + ';'
    if wal.IS_MAC:
        return wildcard

    wildcard += '|'

    wildcard += _('All files (*.*)') + '|'
    wildcard += '*;*.*|'

    for item in items:
        wildcard += descr[item] + '|'
        for extension in ext[item]:
            wildcard += '*.' + extension + ';'
            wildcard += '*.' + extension.upper() + ';'
        if not item == items[-1]:
            wildcard += '|'

    return wildcard


def get_open_file_name(parent, start_dir, msg='', file_types=None):
    file_types = file_types or []
    ret = ''
    msg = msg or _('Open document')
    if wal.IS_MAC:
        msg = ''

    if start_dir == '~':
        start_dir = os.path.expanduser(start_dir)

    style = wx.FD_CHANGE_DIR | wx.FD_FILE_MUST_EXIST | wx.FD_PREVIEW
    dlg = wx.FileDialog(
        parent, message=msg,
        defaultDir=start_dir,
        defaultFile="",
        wildcard=_get_open_filters(file_types),
        style=wx.FD_OPEN | style
    )
    dlg.CenterOnParent()
    if dlg.ShowModal() == wx.ID_OK:
        ret = path_system(dlg.GetPath())
    dlg.Destroy()
    return ret


def _get_save_fiters(items=None):
    items = items or []
    wildcard = ''
    descr = uc2const.FORMAT_DESCRIPTION
    ext = uc2const.FORMAT_EXTENSION
    if not items:
        items = [uc2const.SK2]
    for item in items:
        wildcard += descr[item] + '|'
        for extension in ext[item]:
            wildcard += '*.' + extension + ';'
            wildcard += '*.' + extension.upper() + ';'
        if not item == items[-1]:
            wildcard += '|'
    return wildcard


def get_save_file_name(parent, path, msg='',
                       file_types=None, path_only=False):
    file_types = file_types or []
    ret = None
    msg = msg or _('Save document As...')
    if wal.IS_MAC:
        msg = ''

    if path == '~':
        path = os.path.expanduser(path)

    doc_folder = os.path.dirname(path)
    doc_name = os.path.basename(path)

    style = wx.FD_CHANGE_DIR | wx.FD_OVERWRITE_PROMPT | wx.FD_PREVIEW
    dlg = wx.FileDialog(
        parent, message=msg,
        defaultDir=doc_folder,
        defaultFile=doc_name,
        wildcard=_get_save_fiters(file_types),
        style=wx.FD_SAVE | style
    )
    dlg.CenterOnParent()
    if dlg.ShowModal() == wx.ID_OK:
        if path_only:
            ret = path_system(dlg.GetPath())
            if not file_types:
                ext = uc2const.FORMAT_EXTENSION[uc2const.SK2][0]
            else:
                index = dlg.GetFilterIndex()
                ext = uc2const.FORMAT_EXTENSION[file_types[index]][0]
            ret = os.path.splitext(ret)[0] + '.' + ext
        else:
            ret = (path_system(dlg.GetPath()), dlg.GetFilterIndex())
    dlg.Destroy()
    return ret


def get_dir_path(parent, path='~', msg=''):
    ret = ''
    if not msg:
        msg = _('Select directory')
    if wal.IS_MAC:
        msg = ''

    if path == '~':
        path = os.path.expanduser(path)

    dlg = wx.DirDialog(
        parent, message=msg,
        defaultPath=path,
        style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST
    )
    dlg.CenterOnParent()
    if dlg.ShowModal() == wx.ID_OK:
        ret = path_system(dlg.GetPath())
    dlg.Destroy()
    return ret
