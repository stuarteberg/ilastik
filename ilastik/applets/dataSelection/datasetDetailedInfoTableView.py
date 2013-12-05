from PyQt4.QtCore import pyqtSignal, pyqtSlot, Qt, QUrl, QObject, QEvent
from PyQt4.QtGui import QTableView, QHeaderView, QMenu, QAction, QWidget, \
        QHBoxLayout, QPushButton, QIcon, QItemDelegate

from datasetDetailedInfoTableModel import DatasetDetailedInfoColumn
from addFileButton import AddFileButton, FILEPATH

from functools import partial


class ButtonOverlay(QPushButton):
    """
    Overlay used to show "Remove" button in the row under the cursor.
    """
    def __init__(self, parent = None):
        super(ButtonOverlay, self).__init__(QIcon(FILEPATH +
            "/../../shell/gui/icons/16x16/actions/list-remove.png"),
            "", parent, clicked=self.removeButtonClicked)
        self.setFixedSize(20, 20) # size is fixed based on the icon above
        # these are used to compute placement at the right end of the
        # first column
        self.width = 20
        self.height = 20
        self.setVisible(False)

        # space taken by the headers in tableview
        # the coordinate system is for the whole table, we need to
        # skip the headers to draw in the correct place
        # these will be initialized first time placeAtRow is called
        self.xoffset = None
        self.yoffset = None

        self.current_row = -1

    def removeButtonClicked(self):
        """
        Handles the button click by passing the current row to the parent
        handler.
        """
        assert(self.current_row > -1)
        view = self.parent()
        view.removeButtonClicked(self.current_row)

    def setVisible(self, state):
        """
        Set visibility of the overlay button.

        ``current_row`` is reset when visibility is turned off to make sure
        that we recompute the placement afterwards.
        """
        if state is False:
            self.current_row = -1
        return super(ButtonOverlay, self).setVisible(state)

    def placeAtRow(self, ind):
        """
        Place the button in the row with index ``ind``.
        """
        if ind == self.current_row:
            return
        view = self.parent()
        model = view.model()
        if ind == -1 or ind >= model.rowCount() - 1 or model.isEmptyRow(ind):
            self.setVisible(False)
            return

        # initialize x and y offset if not done already
        if self.yoffset is None:
            self.yoffset = view.horizontalHeader().sizeHint().height() + \
                    2 # nudge a little lower
        if self.xoffset is None:
            self.xoffset = view.verticalHeader().sizeHint().width()

        # avoid painting over the header
        row_y_offset = view.rowViewportPosition(ind)
        if row_y_offset < 0:
            self.setVisible(False)
            return

        # we're on
        column_width = view.columnWidth(0)
        row_height = view.rowHeight(ind)

        self.setGeometry(self.xoffset + column_width - self.width,
                row_y_offset + self.yoffset + (row_height - self.height)/2,
                self.width, self.height)
        self.setVisible(True)
        self.current_row = ind


class DisableButtonOverlayOnMouseEnter(QObject):
    """
    Event filter to disable the button overlay if mouse enters the widget.

    This is used on the horizontal and vertical headers of the table
    view to prevent the remove button from being displayed.
    """
    def __init__(self, parent, overlay):
        super(DisableButtonOverlayOnMouseEnter, self).__init__(parent)
        self._overlay = overlay

    def eventFilter(self, object, event):
        if event.type() == QEvent.Enter:
            self._overlay.setVisible(False)
        return False

class AddButtonDelegate(QItemDelegate):
    """
    Displays an "Add..." button on the first column of the table if the
    corresponding row has not been assigned data yet. This is needed when a
    prediction map for a raw data lane needs to be specified for example.
    """
    def __init__(self, parent):
        super(AddButtonDelegate, self).__init__(parent)

    def paint(self, painter, option, index):
        # This method will be called every time a particular cell is in
        # view and that view is changed in some way. We ask the delegates
        # parent (in this case a table view) if the index in question (the
        # table cell) corresponds to an empty row (indicated by '<empty>'
        # in the data field), and create a button if there isn't one
        # already associated with the cell.
        parent_view = self.parent()
        button = parent_view.indexWidget(index)
        if index.row() < parent_view.model().rowCount()-1 and parent_view.model().isEmptyRow(index.row()):
            if not button:
                button = AddFileButton(parent_view)
                button.addFilesRequested.connect(
                        partial(parent_view.handleCellAddFilesEvent, index.row()))
                button.addStackRequested.connect(
                        partial(parent_view.handleCellAddStackEvent, index.row()))

                parent_view.setIndexWidget(index, button)
            else:
                button.setVisible(True)
        elif index.data() != '':
            # The button needs to be removed when a file is added to the
            # row. Otherwise, it can steal events from the parent view, even if it isn't visible.
            # Also, since the last row of the table also has an add
            # button, before disabling it we check that there is actual
            # data in the cell.
            if button is not None:
                parent_view.setIndexWidget(index, None)
        super(AddButtonDelegate, self).paint(painter, option, index)

class DatasetDetailedInfoTableView(QTableView):
    dataLaneSelected = pyqtSignal(object) # Signature: (laneIndex)

    replaceWithFileRequested = pyqtSignal(int) # Signature: (laneIndex), or (-1) to indicate "append requested"
    replaceWithStackRequested = pyqtSignal(int) # Signature: (laneIndex)
    editRequested = pyqtSignal(object) # Signature: (lane_index_list)
    resetRequested = pyqtSignal(object) # Signature: (lane_index_list)

    addFilesRequested = pyqtSignal(int) # Signature: (lane_index)
    addStackRequested = pyqtSignal(int) # Signature: (lane_index)
    addFilesRequestedDrop = pyqtSignal(object) # Signature: ( filepath_list )

    def __init__(self, parent):
        super( DatasetDetailedInfoTableView, self ).__init__(parent)
        # this is needed to capture mouse events that are used for
        # the remove button placement
        self.setMouseTracking(True)

        self.selectedLanes = []
        self.setContextMenuPolicy( Qt.CustomContextMenu )
        self.customContextMenuRequested.connect( self.handleCustomContextMenuRequested )

        self.resizeRowsToContents()
        self.resizeColumnsToContents()
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.horizontalHeader().setResizeMode(DatasetDetailedInfoColumn.Nickname, QHeaderView.Interactive)
        self.horizontalHeader().setResizeMode(DatasetDetailedInfoColumn.Location, QHeaderView.Interactive)
        self.horizontalHeader().setResizeMode(DatasetDetailedInfoColumn.InternalID, QHeaderView.Interactive)
        self.horizontalHeader().setResizeMode(DatasetDetailedInfoColumn.AxisOrder, QHeaderView.Interactive)

        self.setItemDelegateForColumn(0, AddButtonDelegate(self))
        
        self.setSelectionBehavior( QTableView.SelectRows )
        
        self.setAcceptDrops(True)

        self.overlay = ButtonOverlay(self)

        event_filter = DisableButtonOverlayOnMouseEnter(self, self.overlay)
        self.horizontalHeader().installEventFilter(event_filter)
        self.verticalHeader().installEventFilter(event_filter)

    @pyqtSlot(int)
    def handleCellAddFilesEvent(self, row):
        self.addFilesRequested.emit(row)
        self.sender().setVisible(False)

    @pyqtSlot(int)
    def handleCellAddStackEvent(self, row):
        self.addStackRequested.emit(row)
        self.sender().setVisible(False)

    def wheelEvent(self, event):
        """
        Handle mouse wheel scroll by updating the remove button overlay.
        """
        res = super(DatasetDetailedInfoTableView, self).wheelEvent(event)
        self.adjustRemoveButton(event.pos())
        return res

    def leaveEvent(self, event):
        """
        Disable the remove button overlay when mouse leaves this widget.
        """
        self.overlay.setVisible(False)
        return super(DatasetDetailedInfoTableView, self).enterEvent(event)

    def mouseMoveEvent(self, event=None):
        """
        Update the remove button overlay according to the new mouse
        position.
        """
        self.adjustRemoveButton(event.pos())
        return super(DatasetDetailedInfoTableView, self).mouseMoveEvent(event)

    def adjustRemoveButton(self, pos):
        """
        Move the remove button overlay to the row under the cursor
        position given by ``pos``.
        """
        ind = self.indexAt(pos)
        if ind.column() == -1:
            # disable remove button if not cursor is not over a column
            self.overlay.setVisible(False)
            return

        row_ind = ind.row()
        self.overlay.placeAtRow(row_ind)

    def removeButtonClicked(self, ind):
        """
        Handle remove file events generated by the remove button overlay.
        """
        assert(ind <= self.model().rowCount() - 1)
        self.resetRequested.emit([ind])
        # redraw the table and disable the overlay
        self.overlay.setVisible(False)
        self.update()

    def setModel(self, model):
        """
        Set model used to store the data. This method adds an extra row
        at the end, which is used to keep the "Add..." button.
        """
        super( DatasetDetailedInfoTableView, self ).setModel(model)

        widget = QWidget()
        layout = QHBoxLayout(widget)
        self._addButton = button = AddFileButton(widget, new=True)
        button.addFilesRequested.connect(
                partial(self.addFilesRequested.emit, -1))
        button.addStackRequested.connect(
                partial(self.addStackRequested.emit, -1))
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(button)
        layout.addStretch()
        widget.setLayout(layout)

        lastRow = self.model().rowCount()-1
        modelIndex = self.model().index( lastRow, 0 )
        self.setIndexWidget( modelIndex, widget )
        # the "Add..." button spans last row
        self.setSpan(lastRow, 0, 1, model.columnCount())

    def setEnabled(self, status):
        """
        Set status of the add button shown on the last row.

        If this view is used for a secondary role, such as importing
        prediction maps, the button is only available if there are more
        raw data lanes than prediction maps.
        """
        self._addButton.setEnabled(status)

    def dataChanged(self, topLeft, bottomRight):
        self.dataLaneSelected.emit( self.selectedLanes )

    def selectionChanged(self, selected, deselected):
        super( DatasetDetailedInfoTableView, self ).selectionChanged(selected, deselected)
        # Get the selected row and corresponding slot value
        selectedIndexes = self.selectedIndexes()
        
        if len(selectedIndexes) == 0:
            self.selectedLanes = []
        else:
            rows = set()
            for index in selectedIndexes:
                rows.add(index.row())
            rows.discard(self.model().rowCount() - 1) # last row is a button
            self.selectedLanes = sorted(rows)

        self.dataLaneSelected.emit(self.selectedLanes)
        
    def handleCustomContextMenuRequested(self, pos):
        col = self.columnAt( pos.x() )
        row = self.rowAt( pos.y() )
        
        if 0 <= col < self.model().columnCount() and \
                0 <= row < self.model().rowCount() - 1: # last row is a button
            menu = QMenu(parent=self)
            editSharedPropertiesAction = QAction( "Edit shared properties...", menu )
            editPropertiesAction = QAction( "Edit properties...", menu )
            replaceWithFileAction = QAction( "Replace with file...", menu )
            replaceWithStackAction = QAction( "Replace with stack...", menu )
            
            if self.model().getNumRoles() > 1:
                resetSelectedAction = QAction( "Reset", menu )
            else:
                resetSelectedAction = QAction( "Remove", menu )

            if row in self.selectedLanes and len(self.selectedLanes) > 1:
                editable = True
                for lane in self.selectedLanes:
                    editable &= self.model().isEditable(lane)

                # Show the multi-lane menu, which allows for editing but not replacing
                menu.addAction( editSharedPropertiesAction )
                editSharedPropertiesAction.setEnabled(editable)
                menu.addAction( resetSelectedAction )
            else:
                menu.addAction( editPropertiesAction )
                editPropertiesAction.setEnabled(self.model().isEditable(row))
                menu.addAction( replaceWithFileAction )
                menu.addAction( replaceWithStackAction )
                menu.addAction( resetSelectedAction )
    
            globalPos = self.viewport().mapToGlobal( pos )
            selection = menu.exec_( globalPos )
            if selection is None:
                return
            if selection is editSharedPropertiesAction:
                self.editRequested.emit( self.selectedLanes )
            if selection is editPropertiesAction:
                self.editRequested.emit( [row] )
            if selection is replaceWithFileAction:
                self.replaceWithFileRequested.emit( row )
            if selection is replaceWithStackAction:
                self.replaceWithStackRequested.emit( row )
            if selection is resetSelectedAction:
                self.resetRequested.emit( self.selectedLanes )

    def mouseDoubleClickEvent(self, event):
        col = self.columnAt( event.pos().x() )
        row = self.rowAt( event.pos().y() )

        # If the user double-clicked an empty table,
        #  we behave as if she clicked the "add file" button.
        if self.model().rowCount() == 0:
            # In this case -1 means "append a row"
            self.replaceWithFileRequested.emit(-1)
            return

        if not ( 0 <= col < self.model().columnCount() and 0 <= row < self.model().rowCount() ):
            return

        if self.model().isEditable(row):
            self.editRequested.emit([row])
        else:
            self.replaceWithFileRequested.emit(row)

    def dragEnterEvent(self, event):
        # Only accept drag-and-drop events that consist of urls to local files.
        if not event.mimeData().hasUrls():
            return
        urls = event.mimeData().urls()
        if all( map( QUrl.isLocalFile, urls ) ):        
            event.acceptProposedAction()
        
    def dragMoveEvent(self, event):
        # Must override this or else the QTableView base class steals dropEvents from us.
        pass

    def dropEvent(self, dropEvent):
        urls = dropEvent.mimeData().urls()
        filepaths = map( QUrl.toLocalFile, urls )
        filepaths = map( str, filepaths )
        self.addFilesRequestedDrop.emit( filepaths )
