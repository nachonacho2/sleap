"""
Drop-in replacement for QSlider with additional features.
"""

from PySide2 import QtCore, QtWidgets, QtGui
from PySide2.QtGui import QPen, QBrush, QColor, QKeyEvent, QPolygonF, QPainterPath

from sleap.gui.color import ColorManager

import attr
import itertools
import numpy as np
from typing import Dict, Iterable, List, Optional, Tuple, Union


@attr.s(auto_attribs=True, cmp=False)
class SliderMark:
    """
    Class to hold data for an individual mark on the slider.

    Attributes:
        type: Type of the mark, options are:
            * "simple" (single value)
            * "filled" (single value)
            * "open" (single value)
            * "predicted" (single value)
            * "track" (range of values)
            * "tick" (single value)
            * "tick_column" (single value)
        val: Beginning of mark range
        end_val: End of mark range (for "track" marks)
        row: The row that the mark goes in; used for tracks.
        color: Color of mark, can be string or (r, g, b) tuple.
        filled: Whether the mark is shown filled (solid color).
    """

    type: str
    val: float
    end_val: float = None
    row: int = None
    track: "Track" = None
    _color: Union[tuple, str] = "black"

    @property
    def color(self):
        """Returns color of mark."""
        colors = dict(
            simple="black",
            filled="blue",
            open="blue",
            predicted="yellow",
            tick="lightGray",
            tick_column="gray",
        )

        if self.type in colors:
            return colors[self.type]
        else:
            return self._color

    @color.setter
    def color(self, val):
        """Sets color of mark."""
        self._color = val

    @property
    def QColor(self):
        """Returns color of mark as `QColor`."""
        c = self.color
        if type(c) == str:
            return QColor(c)
        else:
            return QColor(*c)

    @property
    def filled(self):
        """Returns whether mark is filled or open."""
        if self.type == "open":
            return False
        else:
            return True

    @property
    def top_pad(self):
        if self.type == "tick_column":
            return 40
        if self.type == "tick":
            return 0
        return 2

    @property
    def bottom_pad(self):
        if self.type == "tick_column":
            return 200
        if self.type == "tick":
            return 0
        return 2

    @property
    def visual_width(self):
        if self.type in ("open", "filled", "tick"):
            return 2
        if self.type in ("tick_column"):
            return 1
        return 0

    def get_height(self, container_height):
        if self.type == "track":
            return 2
        height = container_height
        # if self.padded:
        height -= self.top_pad + self.bottom_pad

        return height


class VideoSlider(QtWidgets.QGraphicsView):
    """Drop-in replacement for QSlider with additional features.

    Args:
        orientation: ignored (here for compatibility with QSlider)
        min: initial minimum value
        max: initial maximum value
        val: initial value
        marks: initial set of values to mark on slider
            this can be either
            * list of values to mark
            * list of (track, value)-tuples to mark
        color_manager: A :class:`ColorManager` which determines the
            color to use for "track"-type marks

    Signals:
        mousePressed: triggered on Qt event
        mouseMoved: triggered on Qt event
        mouseReleased: triggered on Qt event
        keyPress: triggered on Qt event
        keyReleased: triggered on Qt event
        valueChanged: triggered when value of slider changes
        selectionChanged: triggered when slider range selection changes
        heightUpdated: triggered when the height of slider changes
    """

    mousePressed = QtCore.Signal(float, float)
    mouseMoved = QtCore.Signal(float, float)
    mouseReleased = QtCore.Signal(float, float)
    keyPress = QtCore.Signal(QKeyEvent)
    keyRelease = QtCore.Signal(QKeyEvent)
    valueChanged = QtCore.Signal(int)
    selectionChanged = QtCore.Signal(int, int)
    heightUpdated = QtCore.Signal()

    def __init__(
        self,
        orientation=-1,  # for compatibility with QSlider
        min=0,
        max=100,
        val=0,
        marks=None,
        color_manager: Optional[ColorManager] = None,
        *args,
        **kwargs,
    ):
        super(VideoSlider, self).__init__(*args, **kwargs)

        self.scene = QtWidgets.QGraphicsScene()
        self.setScene(self.scene)
        self.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)

        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

        self._color_manager = color_manager

        self.zoom_factor = 1

        self._track_rows = 0
        self._track_height = 5
        self._max_tracks_stacked = 120
        self._track_stack_skip_count = 10
        self._header_label_height = 20
        self._header_graph_height = 30
        self._header_height = self._header_label_height  # room for frame labels
        self._min_height = 19 + self._header_height

        self._base_font = QtGui.QFont()
        self._base_font.setPixelSize(10)

        self._tick_marks = []

        # Add border rect
        outline_rect = QtCore.QRectF(0, 0, 200, self._min_height - 3)
        self.setBoxRect(outline_rect)
        # self.outlineBox = self.scene.addRect(outline_rect)
        # self.outlineBox.setPen(QPen(QColor("black", alpha=0)))

        # Add drag handle rect
        handle_width = 6
        handle_rect = QtCore.QRect(
            0, self._handleTop(), handle_width, self._handleHeight()
        )
        self.setMinimumHeight(self._min_height)
        self.setMaximumHeight(self._min_height)
        self.handle = self.scene.addRect(handle_rect)
        self.handle.setPen(QPen(QColor(80, 80, 80)))
        self.handle.setBrush(QColor(128, 128, 128, 128))

        # Add (hidden) rect to highlight selection
        self.select_box = self.scene.addRect(
            QtCore.QRect(0, 1, 0, outline_rect.height() - 2)
        )
        self.select_box.setPen(QPen(QColor(80, 80, 255)))
        self.select_box.setBrush(QColor(80, 80, 255, 128))
        self.select_box.hide()

        self.zoom_box = self.scene.addRect(
            QtCore.QRect(0, 1, 0, outline_rect.height() - 2)
        )
        self.zoom_box.setPen(QPen(QColor(80, 80, 80, 64)))
        self.zoom_box.setBrush(QColor(80, 80, 80, 64))
        self.zoom_box.hide()

        self.scene.setBackgroundBrush(QBrush(QColor(200, 200, 200)))

        self.clearSelection()
        self.setEnabled(True)
        self.setMinimum(min)
        self.setMaximum(max)
        self.setValue(val)
        self.setMarks(marks)

        pen = QPen(QColor(80, 80, 255), 0.5)
        pen.setCosmetic(True)
        self.poly = self.scene.addPath(QPainterPath(), pen, self.select_box.brush())
        self.headerSeries = dict()
        self.drawHeader()

    def _pointsToPath(self, points: List[QtCore.QPointF]) -> QPainterPath:
        """Converts list of `QtCore.QPointF` objects to a `QPainterPath`."""
        path = QPainterPath()
        path.addPolygon(QPolygonF(points))
        return path

    def setTracksFromLabels(self, labels: "Labels", video: "Video"):
        """Set slider marks using track information from `Labels` object.

        Note that this is the only method coupled to a SLEAP object.

        Args:
            labels: the dataset with tracks and labeled frames
            video: the video for which to show marks

        Returns:
            None
        """

        if self._color_manager is None:
            self._color_manager = ColorManager(labels=labels)

        lfs = labels.find(video)

        slider_marks = []
        track_row = 0

        # Add marks with track
        track_occupancy = labels.get_track_occupany(video)
        for track in labels.tracks:
            if track in track_occupancy and not track_occupancy[track].is_empty:
                if track_row > 0 and self.isNewColTrack(track_row):
                    slider_marks.append(
                        SliderMark("tick_column", val=track_occupancy[track].start)
                    )
                for occupancy_range in track_occupancy[track].list:
                    slider_marks.append(
                        SliderMark(
                            "track",
                            val=occupancy_range[0],
                            end_val=occupancy_range[1],
                            row=track_row,
                            color=self._color_manager.get_track_color(track),
                        )
                    )
                track_row += 1

        # Add marks without track
        if None in track_occupancy:
            for occupancy_range in track_occupancy[None].list:
                for val in range(*occupancy_range):
                    slider_marks.append(SliderMark("simple", val=val))

        # list of frame_idx for simple markers for labeled frames
        labeled_marks = [lf.frame_idx for lf in lfs]
        user_labeled = [lf.frame_idx for lf in lfs if len(lf.user_instances)]

        for frame_idx in labels.get_video_suggestions(video):
            if frame_idx in user_labeled:
                mark_type = "filled"
            elif frame_idx in labeled_marks:
                mark_type = "predicted"
            else:
                mark_type = "open"
            slider_marks.append(SliderMark(mark_type, val=frame_idx))

        self.setTracks(track_row)  # total number of tracks to show
        self.setMarks(slider_marks)

    def setHeaderSeries(self, series: Optional[Dict[int, float]] = None):
        """Show header graph with specified series.

        Args:
            series: {frame number: series value} dict.
        Returns:
            None.
        """
        self.headerSeries = [] if series is None else series
        self._header_height = self._header_label_height + self._header_graph_height
        self.drawHeader()
        self.updateHeight()

    def clearHeader(self):
        """Remove header graph from slider."""
        self.headerSeries = []
        self._header_height = self._header_label_height
        self.updateHeight()

    def setTracks(self, track_rows):
        """Set the number of tracks to show in slider.

        Args:
            track_rows: the number of tracks to show
        """
        self._track_rows = track_rows
        self.updateHeight()

    def getMinMaxHeights(self):
        tracks = self._track_rows
        if tracks == 0:
            min_height = self._min_height
            max_height = self._min_height
        else:
            # Start with padding height
            extra_height = 8 + self._header_height
            min_height = extra_height
            max_height = extra_height

            # Add height for tracks
            min_height += self._track_height * min(tracks, 20)
            max_height += self._track_height * min(tracks, self._max_tracks_stacked)

            # Make sure min/max height is at least 19, even if few tracks
            min_height = max(self._min_height, min_height)
            max_height = max(self._min_height, max_height)

        return min_height, max_height

    def updateHeight(self):
        """Update the height of the slider."""

        min_height, max_height = self.getMinMaxHeights()

        self.setMaximumHeight(max_height)
        self.setMinimumHeight(min_height)

        # Redraw all marks with new height and y position
        marks = self.getMarks()
        self.setMarks(marks)

        self.resizeEvent()
        self.heightUpdated.emit()

    def _toPos(self, val: float, center=False) -> float:
        """
        Converts slider value to x position on slider.

        Args:
            val: The slider value.
            center: Whether to offset by half the width of drag handle,
                so that plotted location will light up with center of handle.

        Returns:
            x position.
        """
        x = val
        x -= self._val_min
        x /= max(1, self._val_max - self._val_min)
        x *= self._sliderWidth()
        if center:
            x += self.handle.rect().width() / 2.0
        return x

    def _toVal(self, x: float, center=False) -> float:
        """Converts x position to slider value."""
        val = x
        val /= self._sliderWidth()
        val *= max(1, self._val_max - self._val_min)
        val += self._val_min
        val = round(val)
        return val

    def _sliderWidth(self) -> float:
        """Returns visual width of slider."""
        return self.getBoxRect().width() - self.handle.rect().width()

    @property
    def slider_visible_value_range(self) -> float:
        """Value range that's visible given current size and zoom."""
        return self._toVal(self.width() - 1)

    def value(self) -> float:
        """Returns value of slider."""
        return self._val_main

    def setValue(self, val: float) -> float:
        """Sets value of slider."""
        self._val_main = val
        x = self._toPos(val)
        self.handle.setPos(x, 0)
        self.ensureVisible(self.handle, 0, 0)

    def setMinimum(self, min: float) -> float:
        """Sets minimum value for slider."""
        self._val_min = min

    def setMaximum(self, max: float) -> float:
        """Sets maximum value for slider."""
        self._val_max = max

    @property
    def value_range(self) -> float:
        return self._val_max - self._val_min

    def setEnabled(self, val: float) -> float:
        """Set whether the slider is enabled."""
        self._enabled = val

    def enabled(self):
        """Returns whether slider is enabled."""
        return self._enabled

    def clearSelection(self):
        """Clears selection endpoints."""
        self._selection = []
        self.select_box.hide()

    def startSelection(self, val):
        """Adds initial selection endpoint.

        Called when user starts dragging to select range in slider.

        Args:
            val: value of endpoint
        """
        self._selection.append(val)

    def endSelection(self, val, update: bool = False):
        """Add final selection endpoint.

        Called during or after the user is dragging to select range.

        Args:
            val: value of endpoint
            update:
        """
        # If we want to update endpoint and there's already one, remove it
        if update and len(self._selection) % 2 == 0:
            self._selection.pop()
        # Add the selection endpoint
        self._selection.append(val)
        a, b = self._selection[-2:]
        if a == b:
            self.clearSelection()
        else:
            self.drawSelection(a, b)
        # Emit signal (even if user selected same region as before)
        self.selectionChanged.emit(*self.getSelection())

    def setSelection(self, start_val, end_val):
        """Selects clip from start_val to end_val."""
        self.startSelection(start_val)
        self.endSelection(end_val, update=True)

    def hasSelection(self) -> bool:
        """Returns True if a clip is selected, False otherwise."""
        a, b = self.getSelection()
        return a < b

    def getSelection(self):
        """Returns start and end value of current selection endpoints."""
        a, b = 0, 0
        if len(self._selection) % 2 == 0 and len(self._selection) > 0:
            a, b = self._selection[-2:]
        start = min(a, b)
        end = max(a, b)
        return start, end

    def drawSelection(self, a: float, b: float):
        self.updateSelectionBoxPositions(self.select_box, a, b)

    def drawZoomBox(self, a: float, b: float):
        self.updateSelectionBoxPositions(self.zoom_box, a, b)

    def updateSelectionBoxPositions(self, box_object, a: float, b: float):
        """Update box item on slider.

        Args:
            box_object: The box to update
            a: one endpoint value
            b: other endpoint value

        Returns:
            None.
        """
        start = min(a, b)
        end = max(a, b)
        start_pos = self._toPos(start, center=True)
        end_pos = self._toPos(end, center=True)
        box_rect = QtCore.QRect(
            start_pos,
            self._header_height,
            end_pos - start_pos,
            self.getBoxRect().height(),
        )

        box_object.setRect(box_rect)
        box_object.show()

    def updateSelectionBoxesOnResize(self):
        for box_object in (self.select_box, self.zoom_box):
            rect = box_object.rect()
            rect.setHeight(self._handleHeight())
            box_object.setRect(rect)

        if self.select_box.isVisible():
            self.drawSelection(*self.getSelection())

    def moveSelectionAnchor(self, x: float, y: float):
        """
        Moves selection anchor in response to mouse position.

        Args:
            x: x position of mouse
            y: y position of mouse

        Returns:
            None.
        """
        x = max(x, 0)
        x = min(x, self.getBoxRect().width())
        anchor_val = self._toVal(x, center=True)

        if len(self._selection) % 2 == 0:
            self.startSelection(anchor_val)

        self.drawSelection(anchor_val, self._selection[-1])

    def releaseSelectionAnchor(self, x, y):
        """
        Finishes selection in response to mouse release.

        Args:
            x: x position of mouse
            y: y position of mouse

        Returns:
            None.
        """
        x = max(x, 0)
        x = min(x, self.getBoxRect().width())
        anchor_val = self._toVal(x)
        self.endSelection(anchor_val)

    def moveZoomDrag(self, x: float, y: float):
        if getattr(self, "_zoom_start_val", None) is None:
            self._zoom_start_val = self._toVal(x, center=True)

        current_val = self._toVal(x, center=True)

        self.drawZoomBox(current_val, self._zoom_start_val)

    def releaseZoomDrag(self, x, y):

        self.zoom_box.hide()

        val_a = self._zoom_start_val
        val_b = self._toVal(x, center=True)

        val_start = min(val_a, val_b)
        val_end = max(val_a, val_b)

        # pad the zoom
        val_range = val_end - val_start
        val_start -= val_range * 0.05
        val_end += val_range * 0.05

        self.setZoomRange(val_start, val_end)

        self._zoom_start_val = None

    def setZoomRange(self, start_val: float, end_val: float):

        zoom_val_range = end_val - start_val
        if zoom_val_range > 0:
            self.zoom_factor = self.value_range / zoom_val_range
        else:
            self.zoom_factor = 1

        self.resizeEvent()

        center_val = start_val + zoom_val_range / 2
        center_pos = self._toPos(center_val)

        self.centerOn(center_pos, 0)

    def clearMarks(self):
        """Clears all marked values for slider."""
        if hasattr(self, "_mark_items"):
            for item in self._mark_items.values():
                self.scene.removeItem(item)

        if hasattr(self, "_mark_labels"):
            for item in self._mark_labels.values():
                self.scene.removeItem(item)

        self._marks = set()  # holds mark position
        self._mark_items = dict()  # holds visual Qt object for plotting mark
        self._mark_labels = dict()

    def setMarks(self, marks: Iterable[Union[SliderMark, int]]):
        """Sets all marked values for the slider.

        Args:
            marks: iterable with all values to mark

        Returns:
            None.
        """
        self.clearMarks()

        # Add tick marks first so they're behind other marks
        self._add_tick_marks()

        if marks is not None:
            for mark in marks:
                if not isinstance(mark, SliderMark):
                    mark = SliderMark("simple", mark)
                self.addMark(mark, update=False)

        self.updatePos()

    def setTickMarks(self):
        """Resets which tick marks to show."""
        self._clear_tick_marks()
        self._add_tick_marks()

    def _clear_tick_marks(self):
        if not hasattr(self, "_tick_marks"):
            return

        for mark in self._tick_marks:
            self.removeMark(mark)

    def _add_tick_marks(self):
        val_range = self.slider_visible_value_range

        val_order = 10
        while val_range // val_order > 24:
            val_order *= 10

        self._tick_marks = []

        for tick_pos in range(self._val_min + val_order - 1, self._val_max, val_order):
            self._tick_marks.append(SliderMark("tick", tick_pos))

        for tick_mark in self._tick_marks:
            self.addMark(tick_mark, update=False)

    def removeMark(self, mark: SliderMark):
        """Removes an individual mark."""
        if mark in self._mark_labels:
            self.scene.removeItem(self._mark_labels[mark])
            del self._mark_labels[mark]
        if mark in self._mark_items:
            self.scene.removeItem(self._mark_items[mark])
            del self._mark_items[mark]
        if mark in self._marks:
            self._marks.remove(mark)

    def getMarks(self, type: str = ""):
        """Returns list of marks."""
        if type:
            return [mark for mark in self._marks if mark.type == type]

        return self._marks

    def addMark(self, new_mark: SliderMark, update: bool = True):
        """Adds a marked value to the slider.

        Args:
            new_mark: value to mark
            update: Whether to redraw slider with new mark.

        Returns:
            None.
        """
        # check if mark is within slider range
        if new_mark.val > self._val_max:
            return
        if new_mark.val < self._val_min:
            return

        self._marks.add(new_mark)

        v_top_pad = self._header_height + 1
        v_bottom_pad = 1
        v_top_pad += new_mark.top_pad
        v_bottom_pad += new_mark.bottom_pad

        width = new_mark.visual_width

        v_offset = v_top_pad
        if new_mark.type == "track":
            v_offset += self.getTrackVerticalPos(*self.getTrackColRow(new_mark.row))

        height = new_mark.get_height(
            container_height=self.getBoxRect().height() - self._header_height
        )

        color = new_mark.QColor
        pen = QPen(color, 0.5)
        pen.setCosmetic(True)
        brush = QBrush(color) if new_mark.filled else QBrush()

        line = self.scene.addRect(-width // 2, v_offset, width, height, pen, brush)
        self._mark_items[new_mark] = line

        if new_mark.type == "tick":
            # Show tick mark behind other slider marks
            self._mark_items[new_mark].setZValue(0)

            # Add a text label to show in header area
            mark_label_text = f"{new_mark.val + 1:g}"  # sci notation if large
            self._mark_labels[new_mark] = self.scene.addSimpleText(
                mark_label_text, self._base_font
            )
        else:
            # Show in front of tick marks
            self._mark_items[new_mark].setZValue(1)

        if update:
            self.updatePos()

    def getTrackColRow(self, raw_row: int) -> Tuple[int, int]:
        if raw_row < self._max_tracks_stacked:
            return 0, raw_row

        else:
            rows_after_first_col = raw_row - self._max_tracks_stacked
            rows_per_later_cols = (
                self._max_tracks_stacked - self._track_stack_skip_count
            )

            rows_down = rows_after_first_col % rows_per_later_cols
            col = (rows_after_first_col // rows_per_later_cols) + 1

            return col, rows_down

    def getTrackVerticalPos(self, col: int, row: int) -> int:
        if col == 0:
            return row * self._track_height
        else:
            return (self._track_height * self._track_stack_skip_count) + (
                self._track_height * row
            )

    def isNewColTrack(self, row: int) -> bool:
        _, row_down = self.getTrackColRow(row)
        return row_down == 0

    def updatePos(self):
        """Update the visual x position of handle and slider annotations."""
        x = self._toPos(self.value())
        self.handle.setPos(x, 0)

        for mark in self._mark_items.keys():

            if mark.type == "track":
                width_in_frames = mark.end_val - mark.val
                width = max(2, self._toPos(width_in_frames))

            else:
                width = mark.visual_width

            x = self._toPos(mark.val, center=True)
            self._mark_items[mark].setPos(x, 0)

            if mark in self._mark_labels:
                label_x = max(
                    0, x - self._mark_labels[mark].boundingRect().width() // 2
                )
                self._mark_labels[mark].setPos(label_x, 4)

            rect = self._mark_items[mark].rect()
            rect.setWidth(width)
            rect.setHeight(
                mark.get_height(
                    container_height=self.getBoxRect().height() - self._header_height
                )
            )

            self._mark_items[mark].setRect(rect)

    def _get_header_series_len(self):
        if hasattr(self.headerSeries, "keys"):
            series_frame_max = max(self.headerSeries.keys())
        else:
            series_frame_max = len(self.headerSeries)
        return series_frame_max

    @property
    def _header_series_items(self):
        """Uields (frame idx, val) for header series items."""
        if hasattr(self.headerSeries, "items"):
            for key, val in self.headerSeries.items():
                yield key, val
        else:
            for key in range(len(self.headerSeries)):
                val = self.headerSeries[key]
                yield key, val

    def drawHeader(self):
        """Draw the header graph."""
        if len(self.headerSeries) == 0 or self._header_height == 0:
            self.poly.setPath(QPainterPath())
            return

        series_frame_max = self._get_header_series_len()

        step = series_frame_max // int(self._sliderWidth())
        step = max(step, 1)
        count = series_frame_max // step * step

        sampled = np.full((count), 0.0, dtype=np.float)

        for key, val in self._header_series_items:
            if key < count:
                sampled[key] = val

        sampled = np.max(sampled.reshape(count // step, step), axis=1)
        series = {i * step: sampled[i] for i in range(count // step)}

        series_min = np.min(sampled) - 1
        series_max = np.max(sampled)
        series_scale = (self._header_graph_height) / (series_max - series_min)

        def toYPos(val):
            return self._header_height - ((val - series_min) * series_scale)

        step_chart = False  # use steps rather than smooth line

        points = []
        points.append((self._toPos(0, center=True), toYPos(series_min)))
        for idx, val in series.items():
            points.append((self._toPos(idx, center=True), toYPos(val)))
            if step_chart:
                points.append((self._toPos(idx + step, center=True), toYPos(val)))
        points.append(
            (self._toPos(max(series.keys()) + 1, center=True), toYPos(series_min))
        )

        # Convert to list of QtCore.QPointF objects
        points = list(itertools.starmap(QtCore.QPointF, points))
        self.poly.setPath(self._pointsToPath(points))

    def moveHandle(self, x, y):
        """Move handle in response to mouse position.

        Emits valueChanged signal if value of slider changed.

        Args:
            x: x position of mouse
            y: y position of mouse
        """
        x -= self.handle.rect().width() / 2.0
        x = max(x, 0)
        x = min(x, self.getBoxRect().width() - self.handle.rect().width())

        val = self._toVal(x)

        # snap to nearby mark within handle
        mark_vals = [mark.val for mark in self._marks]
        handle_left = self._toVal(x - self.handle.rect().width() / 2)
        handle_right = self._toVal(x + self.handle.rect().width() / 2)
        marks_in_handle = [
            mark for mark in mark_vals if handle_left < mark < handle_right
        ]
        if marks_in_handle:
            marks_in_handle.sort(key=lambda m: (abs(m - val), m > val))
            val = marks_in_handle[0]

        old = self.value()
        self.setValue(val)

        if old != val:
            self.valueChanged.emit(self._val_main)

    def contiguousSelectionMarksAroundVal(self, val):
        """Selects contiguously marked frames around value."""
        if not self.isMarkedVal(val):
            return

        dec_val = self.getStartContiguousMark(val)
        inc_val = self.getEndContiguousMark(val)

        self.setSelection(dec_val, inc_val)

    def getStartContiguousMark(self, val):
        last_val = val
        dec_val = self.decrementContiguousMarkedVal(last_val)
        while dec_val < last_val and dec_val > self._val_min:
            last_val = dec_val
            dec_val = self.decrementContiguousMarkedVal(last_val)

        return dec_val

    def getEndContiguousMark(self, val):
        last_val = val
        inc_val = self.incrementContiguousMarkedVal(last_val)
        while inc_val > last_val and inc_val < self._val_max:
            last_val = inc_val
            inc_val = self.incrementContiguousMarkedVal(last_val)

        return inc_val

    def isMarkedVal(self, val):
        """Returns whether value has mark."""
        if val in [mark.val for mark in self._marks]:
            return True
        if any(
            mark.val <= val < mark.end_val
            for mark in self._marks
            if mark.type == "track"
        ):
            return True
        return False

    def decrementContiguousMarkedVal(self, val):
        """Decrements value within contiguously marked range if possible."""
        dec_val = min(
            (
                mark.val
                for mark in self._marks
                if mark.type == "track" and mark.val < val <= mark.end_val
            ),
            default=val,
        )
        if dec_val < val:
            return dec_val

        if val - 1 in [mark.val for mark in self._marks]:
            return val - 1

        # Return original value if we can't decrement it w/in contiguous range
        return val

    def incrementContiguousMarkedVal(self, val):
        """Increments value within contiguously marked range if possible."""
        inc_val = max(
            (
                mark.end_val - 1
                for mark in self._marks
                if mark.type == "track" and mark.val <= val < mark.end_val
            ),
            default=val,
        )
        if inc_val > val:
            return inc_val

        if val + 1 in [mark.val for mark in self._marks]:
            return val + 1

        # Return original value if we can't decrement it w/in contiguous range
        return val

    def getBoxRect(self):
        # return self.outlineBox.rect()
        return self._box_rect

    def setBoxRect(self, rect):
        # self.outlineBox.setRect(rect)
        self._box_rect = rect

        # Update the scene rect so that it matches how much space we
        # currently want for drawing everything.
        rect.setWidth(rect.width() - 1)
        self.setSceneRect(rect)

    def getMarkAreaHeight(self):
        _, max_height = self.getMinMaxHeights()
        return max_height - 3 - self._header_height

    def resizeEvent(self, event=None):
        """Override method to update visual size when necessary.

        Args:
            event
        """

        outline_rect = self.getBoxRect()
        handle_rect = self.handle.rect()

        outline_rect.setHeight(self.getMarkAreaHeight() + self._header_height)

        if event is not None:
            visual_width = event.size().width() - 1
        else:
            visual_width = self.width() - 1

        drawn_width = visual_width * self.zoom_factor

        outline_rect.setWidth(drawn_width)
        self.setBoxRect(outline_rect)

        handle_rect.setTop(self._handleTop())
        handle_rect.setHeight(self._handleHeight())
        self.handle.setRect(handle_rect)

        self.updateSelectionBoxesOnResize()

        self.setTickMarks()
        self.updatePos()
        self.drawHeader()

        super(VideoSlider, self).resizeEvent(event)

    def _handleTop(self) -> float:
        """Returns y position of top of handle (i.e., header height)."""
        return 1 + self._header_height

    def _handleHeight(self, outline_rect=None) -> float:
        """
        Returns visual height of handle.

        Args:
            outline_rect: The rect of the outline box for the slider. This
                is only required when calling during initialization (when the
                outline box doesn't yet exist).

        Returns:
            Height of handle in pixels.
        """
        return self.getMarkAreaHeight()

    def mousePressEvent(self, event):
        """Override method to move handle for mouse press/drag.

        Args:
            event
        """
        scenePos = self.mapToScene(event.pos())

        # Do nothing if not enabled
        if not self.enabled():
            return
        # Do nothing if click outside slider area
        if not self.getBoxRect().contains(scenePos):
            return

        move_function = None
        release_function = None

        if event.modifiers() == QtCore.Qt.ShiftModifier:
            move_function = self.moveSelectionAnchor
            release_function = self.releaseSelectionAnchor

            self.clearSelection()

        elif event.modifiers() == QtCore.Qt.NoModifier:
            move_function = self.moveHandle
            release_function = None

        elif event.modifiers() == QtCore.Qt.AltModifier:
            move_function = self.moveZoomDrag
            release_function = self.releaseZoomDrag

        else:
            event.accept()  # mouse events shouldn't be passed to video widgets

        # Connect to signals
        if move_function is not None:
            self.mouseMoved.connect(move_function)

        def done(x, y):
            if release_function is not None:
                release_function(x, y)
            if move_function is not None:
                self.mouseMoved.disconnect(move_function)
            self.mouseReleased.disconnect(done)

        self.mouseReleased.connect(done)

        # Emit signal
        self.mouseMoved.emit(scenePos.x(), scenePos.y())
        self.mousePressed.emit(scenePos.x(), scenePos.y())

    def mouseMoveEvent(self, event):
        """Override method to emid mouseMoved signal on drag."""
        scenePos = self.mapToScene(event.pos())
        self.mouseMoved.emit(scenePos.x(), scenePos.y())

    def mouseReleaseEvent(self, event):
        """Override method to emit mouseReleased signal on release."""
        scenePos = self.mapToScene(event.pos())
        self.mouseReleased.emit(scenePos.x(), scenePos.y())

    def mouseDoubleClickEvent(self, event):
        """Override method to move handle for mouse double-click.

        Args:
            event
        """
        scenePos = self.mapToScene(event.pos())

        # Do nothing if not enabled
        if not self.enabled():
            return
        # Do nothing if click outside slider area
        if not self.getBoxRect().contains(scenePos):
            return

        if event.modifiers() == QtCore.Qt.ShiftModifier:
            self.contiguousSelectionMarksAroundVal(self._toVal(scenePos.x()))

    def keyPressEvent(self, event):
        """Catch event and emit signal so something else can handle event."""
        self.keyPress.emit(event)
        event.accept()

    def keyReleaseEvent(self, event):
        """Catch event and emit signal so something else can handle event."""
        self.keyRelease.emit(event)
        event.accept()

    def boundingRect(self) -> QtCore.QRectF:
        """Method required by Qt."""
        return self.getBoxRect()

    def paint(self, *args, **kwargs):
        """Method required by Qt."""
        super(VideoSlider, self).paint(*args, **kwargs)


if __name__ == "__main__":
    app = QtWidgets.QApplication([])

    window = VideoSlider(
        min=0,
        max=20,
        val=15,
        marks=(10, 15),  # ((0,10),(0,15),(1,10),(1,11),(2,12)), tracks=3
    )

    window.valueChanged.connect(lambda x: print(x))
    window.show()

    app.exec_()
