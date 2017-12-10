# -*- coding: utf-8 -*-
#
# 	Copyright (C) 2013-2015 by Igor E. Novikov
#
# 	This program is free software: you can redistribute it and/or modify
# 	it under the terms of the GNU General Public License as published by
# 	the Free Software Foundation, either version 3 of the License, or
# 	(at your option) any later version.
#
# 	This program is distributed in the hope that it will be useful,
# 	but WITHOUT ANY WARRANTY; without even the implied warranty of
# 	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# 	GNU General Public License for more details.
#
# 	You should have received a copy of the GNU General Public License
# 	along with this program.  If not, see <http://www.gnu.org/licenses/>.

import cairo
import inspect
import wx

import wal
from ctx_menu import ContextMenu
from sk1 import events, modes, config
from sk1.appconst import PAGEFIT, ZOOM_IN, ZOOM_OUT, RENDERING_DELAY
from sk1.document import controllers
from sk1.document.kbd_proc import KbdProcessor
from sk1.document.renderer import PDRenderer
from uc2 import uc2const, libcairo, libgeom
from uc2.libcairo import normalize_bbox
from uc2.sk2const import DOC_ORIGIN_LL, DOC_ORIGIN_LU
from uc2.uc2const import mm_to_pt, point_dict


class CanvasTimer(wx.Timer):
    def __init__(self, parent):
        wx.Timer.__init__(self, parent)

    def is_running(self):
        return self.IsRunning()

    def stop(self):
        if self.IsRunning():
            self.Stop()

    def start(self, interval=RENDERING_DELAY):
        if not self.IsRunning():
            self.Start(interval)


WORKSPACE_HEIGHT = 2000 * mm_to_pt
WORKSPACE_WIDTH = 4000 * mm_to_pt


class AppCanvas(wx.Panel):
    presenter = None
    app = None
    eventloop = None
    renderer = None
    hscroll = None
    vscroll = None
    timer = None
    ctx_menu = None
    hit_surface = None

    mode = None
    previous_mode = None
    controller = None
    ctrls = {}
    current_cursor = None

    workspace = (WORKSPACE_WIDTH, WORKSPACE_HEIGHT)
    matrix = None
    trafo = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    zoom = 1.0
    zoom_stack = []
    width = 0
    height = 0
    orig_cursor = None
    resize_marker = 0

    stroke_view = False
    draft_view = False
    soft_repaint = False
    full_repaint = False
    selection_repaint = True
    mouse_captured = False
    show_snapping = config.show_snap
    dragged_guide = ()

    my_changes = False
    redraw_flag = False
    request_redraw_flag = False

    def __init__(self, presenter, parent):
        self.presenter = presenter
        self.eventloop = self.presenter.eventloop
        self.app = presenter.app
        self.doc = self.presenter.model
        self.renderer = PDRenderer(self)
        style = wx.FULL_REPAINT_ON_RESIZE | wx.WANTS_CHARS
        wx.Panel.__init__(self, parent, style=style)
        self.SetBackgroundColour(wx.Colour(255, 255, 255))
        self.hit_surface = HitSurface(self)
        self.zoom_stack = []

        self.ctx_menu = ContextMenu(self.app, self)

        self.timer = CanvasTimer(self)
        self.Bind(wx.EVT_TIMER, self._on_timer)

        self.ctrls = self.init_controllers()
        self.Bind(wx.EVT_PAINT, self.on_paint, self)
        self.Bind(wx.EVT_ENTER_WINDOW, self.mouse_enter, self)
        # ----- Mouse binding
        self.Bind(wx.EVT_LEFT_DOWN, self.mouse_left_down)
        self.Bind(wx.EVT_LEFT_UP, self.mouse_left_up)
        self.Bind(wx.EVT_LEFT_DCLICK, self.mouse_left_dclick)
        self.Bind(wx.EVT_RIGHT_DOWN, self.mouse_right_down)
        self.Bind(wx.EVT_RIGHT_UP, self.mouse_right_up)
        self.Bind(wx.EVT_MIDDLE_DOWN, self.mouse_middle_down)
        self.Bind(wx.EVT_MIDDLE_UP, self.mouse_middle_up)
        self.Bind(wx.EVT_MOUSEWHEEL, self.mouse_wheel)
        self.Bind(wx.EVT_MOTION, self.mouse_move)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self.capture_lost)
        # ----- Keyboard binding
        self.kbproc = KbdProcessor(self)
        self.Bind(wx.EVT_KEY_DOWN, self.kbproc.on_key_down)
        self.Bind(wx.EVT_CHAR, self.kbproc.on_char)
        # 		self.Bind(wx.EVT_KEY_UP, self.OnKeyUp)
        # ----- Application eventloop bindings
        self.eventloop.connect(self.eventloop.DOC_MODIFIED, self.doc_modified)
        self.eventloop.connect(self.eventloop.PAGE_CHANGED, self.doc_modified)
        self.eventloop.connect(self.eventloop.SELECTION_CHANGED,
                               self.selection_redraw)

    def destroy(self):
        self.timer.stop()
        self.ctx_menu.destroy()
        self.renderer.destroy()
        self.hit_surface.destroy()
        items = self.ctrls.keys()
        for item in items:
            if not inspect.isclass(self.ctrls[item]):
                self.ctrls[item].destroy()
        items = self.__dict__.keys()
        for item in items:
            self.__dict__[item] = None

    def set_focus(self):
        self.SetFocus()

    # ----- SCROLLING

    def _set_scrolls(self, hscroll, vscroll):
        self.hscroll = hscroll
        self.vscroll = vscroll
        self.hscroll.SetScrollbar(500, 100, 1100, 100, refresh=True)
        self.vscroll.SetScrollbar(500, 100, 1100, 100, refresh=True)
        self.hscroll.Bind(wx.EVT_SCROLL, self._scrolling, self.hscroll)
        self.vscroll.Bind(wx.EVT_SCROLL, self._scrolling, self.vscroll)

    def _scrolling(self, *args):
        if self.my_changes:
            return
        xpos = self.hscroll.GetThumbPosition() / 1000.0
        ypos = (1000 - self.vscroll.GetThumbPosition()) / 1000.0
        x = (xpos - 0.5) * self.workspace[0]
        y = (ypos - 0.5) * self.workspace[1]
        center = self.doc_to_win([x, y])
        self._set_center(center)
        self.force_redraw()

    def update_scrolls(self):
        self.my_changes = True
        center = self._get_center()
        x = (center[0] + self.workspace[0] / 2.0) / self.workspace[0]
        y = (center[1] + self.workspace[1] / 2.0) / self.workspace[1]
        hscroll = int(1000 * x)
        vscroll = int(1000 - 1000 * y)
        self.hscroll.SetScrollbar(hscroll, 100, 1100, 100, refresh=True)
        self.vscroll.SetScrollbar(vscroll, 100, 1100, 100, refresh=True)
        self.my_changes = False

    # ----- CONTROLLERS

    def init_controllers(self):
        presenter = self.presenter
        return {
            modes.SELECT_MODE: controllers.SelectController(self, presenter),
            modes.SHAPER_MODE: controllers.EditorChooser,
            modes.BEZIER_EDITOR_MODE: controllers.BezierEditor,
            modes.RECT_EDITOR_MODE: controllers.RectEditor,
            modes.ELLIPSE_EDITOR_MODE: controllers.EllipseEditor,
            modes.POLYGON_EDITOR_MODE: controllers.PolygonEditor,
            modes.TEXT_EDITOR_MODE: controllers.TextEditor,
            modes.ZOOM_MODE: controllers.ZoomController,
            modes.FLEUR_MODE: controllers.FleurController,
            modes.TEMP_FLEUR_MODE: controllers.TempFleurController,
            modes.PICK_MODE: controllers.PickController,
            modes.LINE_MODE: controllers.PolyLineCreator,
            modes.CURVE_MODE: controllers.PathsCreator,
            modes.RECT_MODE: controllers.RectangleCreator,
            modes.ELLIPSE_MODE: controllers.EllipseCreator,
            modes.TEXT_MODE: controllers.TextCreator,
            modes.TEXT_EDIT_MODE: controllers.TextEditController,
            modes.POLYGON_MODE: controllers.PolygonCreator,
            modes.MOVE_MODE: controllers.MoveController,
            modes.RESIZE_MODE: controllers.TransformController,
            modes.GUIDE_MODE: controllers.GuideController,
            modes.WAIT_MODE: controllers.WaitController,
            modes.GR_SELECT_MODE: controllers.GradientChooser,
            modes.GR_CREATE_MODE: controllers.GradientCreator,
            modes.GR_EDIT_MODE: controllers.GradientEditor,
        }

    def get_controller(self, mode):
        ctrl = self.ctrls[mode]
        if inspect.isclass(ctrl):
            self.ctrls[mode] = ctrl(self, self.presenter)
        return self.ctrls[mode]

    def set_mode(self, mode=modes.SELECT_MODE):
        if not mode == self.mode:
            if self.previous_mode is not None:
                self.restore_mode()
            if self.controller is not None:
                self.controller.stop_()
            self.mode = mode
            self.controller = self.get_controller(mode)
            self.controller.set_cursor()
            self.controller.start_()
            events.emit(events.MODE_CHANGED, mode)
            if self.presenter.selection and self.presenter.selection.objs:
                self.presenter.selection.update()

    def set_canvas_cursor(self, mode):
        self.current_cursor = self.app.cursors[mode]
        self.SetCursor(self.current_cursor)

    def set_temp_mode(self, mode=modes.SELECT_MODE, callback=None):
        if not mode == self.mode:
            self.previous_mode = self.mode
            self.ctrls[self.mode].standby()
            self.mode = mode
            self.controller = self.get_controller(mode)
            self.controller.callback = callback
            self.controller.start_()
            self.controller.set_cursor()

    def restore_mode(self):
        if self.previous_mode is not None:
            if self.controller is not None:
                self.controller.stop_()
            self.mode = self.previous_mode
            self.controller = self.get_controller(self.mode)
            self.controller.set_cursor()
            self.controller.restore()
            events.emit(events.MODE_CHANGED, self.mode)
            self.previous_mode = None
        else:
            self.set_mode()

    def set_temp_cursor(self, cursor):
        self.orig_cursor = self.app.cursors[self.mode]
        self.current_cursor = cursor
        self.SetCursor(cursor)

    def restore_cursor(self):
        if self.orig_cursor is not None:
            self.SetCursor(self.orig_cursor)
            self.current_cursor = self.orig_cursor
            self.orig_cursor = None

    def show_context_menu(self):
        self.ctx_menu.rebuild()
        self.PopupMenu(self.ctx_menu)

    # ----- CANVAS MATH

    def _keep_center(self):
        w, h = self.GetSize()
        w = float(w)
        h = float(h)
        if not w == self.width or not h == self.height:
            _dx = (w - self.width) / 2.0
            _dy = (h - self.height) / 2.0
            m11, m12, m21, m22, dx, dy = self.trafo
            dx += _dx
            dy += _dy
            self.trafo = [m11, m12, m21, m22, dx, dy]
            self.matrix = cairo.Matrix(m11, m12, m21, m22, dx, dy)
            self.width = w
            self.height = h
            self.update_scrolls()

    def _set_center(self, center):
        x, y = center
        _dx = self.width / 2.0 - x
        _dy = self.height / 2.0 - y
        m11, m12, m21, m22, dx, dy = self.trafo
        dx += _dx
        dy += _dy
        self.trafo = [m11, m12, m21, m22, dx, dy]
        self.matrix = cairo.Matrix(m11, m12, m21, m22, dx, dy)
        self.update_scrolls()

    def _get_center(self):
        x = self.width / 2.0
        y = self.height / 2.0
        return self.win_to_doc([x, y])

    def doc_to_win(self, point=None):
        point = point or [0.0, 0.0]
        x, y = point
        m11 = self.trafo[0]
        m22, dx, dy = self.trafo[3:]
        x_new = m11 * x + dx
        y_new = m22 * y + dy
        return [x_new, y_new]

    def point_doc_to_win(self, point=None):
        point = point or [0.0, 0.0]
        if not point:
            return []
        if len(point) == 2:
            return self.doc_to_win(point)
        else:
            return [self.doc_to_win(point[0]),
                    self.doc_to_win(point[1]),
                    self.doc_to_win(point[2]), point[3]]

    def win_to_doc(self, point=None):
        point = point or [0, 0]
        x, y = point
        x = float(x)
        y = float(y)
        m11 = self.trafo[0]
        m22, dx, dy = self.trafo[3:]
        x_new = (x - dx) / m11
        y_new = (y - dy) / m22
        return [x_new, y_new]

    def win_to_doc_coords(self, point=None):
        point = point or [0, 0]
        x, y = self.win_to_doc(point)
        origin = self.presenter.model.doc_origin
        w, h = self.presenter.get_page_size()
        if origin == DOC_ORIGIN_LL:
            return [w / 2.0 + x, h / 2.0 + y]
        elif origin == DOC_ORIGIN_LU:
            return [w / 2.0 + x, h / 2.0 - y]
        else:
            return [x, y]

    def point_win_to_doc(self, point=None):
        point = point or [0.0, 0.0]
        if not point:
            return []
        if len(point) == 2:
            return self.win_to_doc(point)
        else:
            return [self.win_to_doc(point[0]),
                    self.win_to_doc(point[1]),
                    self.win_to_doc(point[2]), point[3]]

    def paths_doc_to_win(self, paths):
        result = []
        for path in paths:
            new_path = []
            new_points = []
            new_path.append(self.doc_to_win(path[0]))
            for point in path[1]:
                new_points.append(self.point_doc_to_win(point))
            new_path.append(new_points)
            new_path.append(path[2])
            result.append(new_path)
        return result

    def bbox_win_to_doc(self, bbox):
        new_bbox = self.win_to_doc(bbox[:2]) + self.win_to_doc(bbox[2:])
        return normalize_bbox(new_bbox)

    def bbox_doc_to_win(self, bbox):
        new_bbox = self.doc_to_win(bbox[:2]) + self.doc_to_win(bbox[2:])
        return normalize_bbox(new_bbox)

    def scroll(self, cdx, cdy):
        m11, m12, m21, m22, dx, dy = self.trafo
        dx += cdx
        dy += cdy
        self.trafo = [m11, m12, m21, m22, dx, dy]
        self.zoom_stack.append([] + self.trafo)
        self.matrix = cairo.Matrix(*self.trafo)
        self.update_scrolls()
        self.force_redraw()

    # ----- ZOOMING

    def _fit_to_page(self):
        width, height = self.presenter.get_page_size()
        w, h = self.GetSize()
        w = float(w)
        h = float(h)
        self.width = w
        self.height = h
        zoom = min(w / width, h / height) * PAGEFIT
        dx = w / 2.0
        dy = h / 2.0
        self.trafo = [zoom, 0, 0, -zoom, dx, dy]
        self.zoom_stack.append([] + self.trafo)
        self.matrix = cairo.Matrix(zoom, 0, 0, -zoom, dx, dy)
        self.zoom = zoom
        self.update_scrolls()

    def zoom_fit_to_page(self):
        self._fit_to_page()
        self.force_redraw()

    def _zoom(self, dzoom=1.0):
        m11, m12, m21, m22, dx, dy = self.trafo
        _dx = (self.width * dzoom - self.width) / 2.0
        _dy = (self.height * dzoom - self.height) / 2.0
        dx = dx * dzoom - _dx
        dy = dy * dzoom - _dy
        self.trafo = [m11 * dzoom, m12, m21, m22 * dzoom, dx, dy]
        self.zoom_stack.append([] + self.trafo)
        self.matrix = cairo.Matrix(*self.trafo)
        self.zoom = m11 * dzoom
        self.update_scrolls()
        self.force_redraw()

    def zoom_in(self):
        self._zoom(ZOOM_IN)

    def zoom_out(self):
        self._zoom(ZOOM_OUT)

    def zoom_100(self):
        self._zoom(1.0 / self.zoom)

    def zoom_at_point(self, point, zoom):
        x, y = point
        m11, m12, m21, m22, dx, dy = self.trafo
        dx = dx * zoom - x * zoom + x
        dy = dy * zoom - y * zoom + y
        self.trafo = [m11 * zoom, m12, m21, m22 * zoom, dx, dy]
        self.zoom_stack.append([] + self.trafo)
        self.matrix = cairo.Matrix(*self.trafo)
        self.zoom = m11 * zoom
        self.update_scrolls()
        self.force_redraw()

    def zoom_to_rectangle(self, start, end):
        w, h = self.GetSize()
        w = float(w)
        h = float(h)
        self.width = w
        self.height = h
        width = abs(end[0] - start[0])
        height = abs(end[1] - start[1])
        zoom = min(w / width, h / height) * 0.95
        center = [start[0] + (end[0] - start[0]) / 2,
                  start[1] + (end[1] - start[1]) / 2]
        self._set_center(center)
        self._zoom(zoom)

    def zoom_selected(self):
        x0, y0, x1, y1 = self.presenter.selection.frame
        start = self.doc_to_win([x0, y0])
        end = self.doc_to_win([x1, y1])
        self.zoom_to_rectangle(start, end)

    def zoom_previous(self):
        if len(self.zoom_stack) > 1:
            self.zoom_stack = self.zoom_stack[:-1]
            self.trafo = [] + self.zoom_stack[-1]
            self.zoom = self.trafo[0]
            self.matrix = cairo.Matrix(*self.trafo)
            self.update_scrolls()
            self.force_redraw()

    # ----- SELECTION STUFF

    def select_at_point(self, point, add_flag=False):
        point = self.win_to_doc(point)
        self.presenter.selection.select_at_point(point, add_flag)

    def pick_at_point(self, point):
        point = self.win_to_doc(point)
        return self.presenter.selection.pick_at_point(point)

    def select_by_rect(self, start, end, flag=False):
        start = self.win_to_doc(start)
        end = self.win_to_doc(end)
        rect = start + end
        rect = normalize_bbox(rect)
        self.presenter.selection.select_by_rect(rect, flag)

    # ----- RENDERING -----
    def selection_redraw(self, *args):
        if not self.full_repaint:
            self.soft_repaint = True
        self.force_redraw()

    def doc_modified(self, *args):
        self.full_repaint = True
        self.force_redraw()

    def force_redraw(self, *args):
        if self.redraw_flag:
            self.request_redraw_flag = True
        else:
            w, h = self.GetSize()
            self.redraw_flag = True
            self.Refresh(rect=wx.Rect(0, 0, w, h), eraseBackground=False)

    def on_paint(self, event):
        if self.matrix is None:
            self.zoom_fit_to_page()
            self.set_mode(modes.SELECT_MODE)
        self._keep_center()

        try:
            if self.soft_repaint and not self.full_repaint:
                if self.selection_repaint:
                    if self.mode in modes.EDIT_MODES and \
                            self.presenter.selection.objs:
                        pass
                    else:
                        self.renderer.paint_selection()
                self.soft_repaint = False
            else:
                self.renderer.paint_document()
                if self.selection_repaint:
                    if self.mode in modes.EDIT_MODES and \
                            self.presenter.selection.objs:
                        pass
                    else:
                        self.renderer.paint_selection()
                self.eventloop.emit(self.eventloop.VIEW_CHANGED)
                self.full_repaint = False
                self.soft_repaint = False
            if self.controller is not None:
                self.controller.repaint()
            if self.dragged_guide:
                self.renderer.paint_guide_dragging(*self.dragged_guide)
                if not self.mode == modes.GUIDE_MODE:
                    self.dragged_guide = ()
            self.renderer.finalize()
        except Exception:
            self.app.print_stacktrace()

        self.redraw_flag = False
        if self.request_redraw_flag:
            self.request_redraw_flag = False
            self.force_redraw()

            # ==============EVENT CONTROLLING==========================

    def mouse_enter(self, enent):
        if wal.IS_MSW:
            self.SetFocus()

    def capture_mouse(self):
        if wal.IS_MSW:
            self.CaptureMouse()
            self.mouse_captured = True

    def release_mouse(self):
        if self.mouse_captured:
            try:
                self.ReleaseMouse()
            except Exception:
                pass
            self.mouse_captured = False

    def capture_lost(self, event):
        self.release_mouse()

    def _on_timer(self, event):
        self.controller.on_timer()

    def mouse_left_down(self, event):
        self.capture_mouse()
        self.controller.set_cursor()
        self.controller.mouse_down(CanvasEvent(event))
        event.Skip()

    def mouse_left_up(self, event):
        self.release_mouse()
        self.controller.mouse_up(CanvasEvent(event))

    def mouse_left_dclick(self, event):
        self.controller.set_cursor()
        self.controller.mouse_double_click(CanvasEvent(event))

    def mouse_move(self, event):
        x, y = self.win_to_doc_coords(list(event.GetPositionTuple()))
        unit = self.presenter.model.doc_units
        tr_unit = uc2const.unit_short_names[unit]
        msg = '  %i x %i' % (x * point_dict[unit], y * point_dict[unit])
        events.emit(events.MOUSE_STATUS, '%s %s' % (msg, tr_unit))
        self.controller.mouse_move(CanvasEvent(event))

    def mouse_right_down(self, event):
        self.controller.mouse_right_down(CanvasEvent(event))

    def mouse_right_up(self, event):
        self.controller.mouse_right_up(CanvasEvent(event))

    def mouse_middle_down(self, event):
        self.controller.mouse_middle_down(CanvasEvent(event))

    def mouse_middle_up(self, event):
        self.controller.mouse_middle_up(CanvasEvent(event))

    def mouse_wheel(self, event):
        self.controller.wheel(CanvasEvent(event))


class CanvasEvent(wal.MouseEvent):
    def get_rotation(self):
        return wal.MouseEvent.get_rotation(
            self) / config.mouse_scroll_sensitivity


class HitSurface:
    surface = None
    ctx = None
    canvas = None

    def __init__(self, canvas):
        self.canvas = canvas
        self.surface = cairo.ImageSurface(cairo.FORMAT_RGB24, 1, 1)
        self.ctx = cairo.Context(self.surface)

    def destroy(self):
        items = self.__dict__.keys()
        for item in items:
            self.__dict__[item] = None

    def clear(self):
        self.ctx.set_source_rgb(1, 1, 1)
        self.ctx.paint()
        self.ctx.set_source_rgb(0, 0, 0)

    def get_context_trafo(self, win_point):
        dx, dy = win_point
        trafo = [] + self.canvas.trafo
        trafo[4] -= dx
        trafo[5] -= dy
        return trafo

    def is_point_into_object(self, win_point, obj, fill_anyway=False):
        self.clear()
        self._draw_object(obj, self.get_context_trafo(win_point), fill_anyway)
        return not libcairo.check_surface_whiteness(self.surface)

    def _draw_object(self, obj, trafo, fill_anyway=False):
        if obj.childs:
            for child in obj.childs:
                self._draw_object(child, trafo)
        else:
            path = obj.cache_cpath

            if obj.is_text():
                path = libcairo.convert_bbox_to_cpath(obj.cache_bbox)
                fill_anyway = True
            if obj.is_curve() and len(obj.paths) > 100:
                path = libcairo.convert_bbox_to_cpath(obj.cache_bbox)
                fill_anyway = True
            if obj.is_pixmap():
                fill_anyway = True

            self.ctx.set_matrix(libcairo.get_matrix_from_trafo(trafo))
            self.ctx.new_path()
            self.ctx.append_path(path)
            stroke_width = config.stroke_sensitive_size
            if not self.canvas.stroke_view and obj.style[0]:
                self.ctx.fill_preserve()
            if fill_anyway:
                self.ctx.fill_preserve()
            if obj.style[1]:
                stroke = obj.style[1]
                width = stroke[1] * trafo[0]
                stroke_width /= trafo[0]
                if width < stroke_width:
                    width = stroke_width
                self.ctx.set_line_width(width)
                self.ctx.stroke()

    def is_point_on_path(self, win_point, path):
        self.clear()
        trafo = self.get_context_trafo(win_point)
        self.ctx.set_matrix(libcairo.get_matrix_from_trafo(trafo))
        stroke_width = config.stroke_sensitive_size
        stroke_width /= trafo[0]
        cpath = libgeom.create_cpath([path, ])
        self.ctx.new_path()
        self.ctx.append_path(cpath)
        self.ctx.set_line_width(stroke_width)
        self.ctx.stroke()
        return not libcairo.check_surface_whiteness(self.surface)

    def is_point_on_segment(self, win_point, start_point, end_point):
        self.clear()
        trafo = self.get_context_trafo(win_point)
        self.ctx.set_matrix(libcairo.get_matrix_from_trafo(trafo))
        stroke_width = config.stroke_sensitive_size
        stroke_width /= trafo[0]
        if len(start_point) > 2:
            start_point = start_point[2]
        self.ctx.move_to(*start_point)
        if len(end_point) == 2:
            self.ctx.line_to(*end_point)
        else:
            p1, p2, p3 = end_point[:-1]
            self.ctx.curve_to(*(p1 + p2 + p3))
        self.ctx.set_line_width(stroke_width)
        self.ctx.stroke()
        return not libcairo.check_surface_whiteness(self.surface)

    def get_t_parameter(self, win_point, start, end, t=0.5, dt=0.5):
        dt /= 2.0
        new, new_end = libgeom.split_bezier_curve(start, end, t)
        ret1 = self.is_point_on_segment(win_point, start, new)
        ret2 = self.is_point_on_segment(win_point, new, new_end)
        if ret1 and ret2:
            return t
        elif ret1:
            return self.get_t_parameter(win_point, start, end, t - dt, dt)
        elif ret2:
            return self.get_t_parameter(win_point, start, end, t + dt, dt)
