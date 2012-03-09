# -*- coding: utf-8 -*-

from __future__ import absolute_import
import docflow
from werkzeug.exceptions import Forbidden

__all__ = ['WorkflowStateException', 'WorkflowTransitionException',
    'WorkflowPermissionException', 'WorkflowState', 'WorkflowStateGroup',
    'DocumentWorkflow']


class WorkflowStateException(docflow.WorkflowStateException, Forbidden):
    pass


class WorkflowTransitionException(docflow.WorkflowTransitionException, Forbidden):
    pass


class WorkflowPermissionException(docflow.WorkflowPermissionException, Forbidden):
    pass


class WorkflowState(docflow.WorkflowState):
    __doc__ = docflow.WorkflowState.__doc__

    exception_state = WorkflowStateException
    exception_transition = WorkflowTransitionException
    exception_permission = WorkflowPermissionException


class WorkflowStateGroup(docflow.WorkflowStateGroup):
    __doc__ = docflow.WorkflowStateGroup.__doc__

    exception_state = WorkflowStateException
    exception_transition = WorkflowTransitionException
    exception_permission = WorkflowPermissionException


class DocumentWorkflow(docflow.DocumentWorkflow):
    __doc__ = docflow.DocumentWorkflow.__doc__

    exception_state = WorkflowStateException
