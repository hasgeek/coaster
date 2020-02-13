# -*- coding: utf-8 -*-

"""
Document workflows
==================

Coaster provides versions of the main Docflow_ classes where workflow
exceptions map to HTTP 403 Forbidden (via werkzeug.exceptions.Forbidden_).

.. _Docflow: http://docflow.readthedocs.org/
.. _werkzeug.exceptions.Forbidden:
    http://werkzeug.readthedocs.org/en/latest/exceptions/#werkzeug.exceptions.Forbidden
"""

from __future__ import absolute_import

from flask import g
from werkzeug.exceptions import Forbidden

import docflow

from .auth import current_auth

__all__ = [
    'WorkflowStateException',
    'WorkflowTransitionException',
    'WorkflowPermissionException',
    'WorkflowState',
    'WorkflowStateGroup',
    'InteractiveTransition',
    'DocumentWorkflow',
]


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


class InteractiveTransition(docflow.InteractiveTransition):
    __doc__ = docflow.InteractiveTransition.__doc__

    def __init__(self, workflow):
        super(InteractiveTransition, self).__init__(workflow)
        if hasattr(self, 'formclass'):
            self.form = self.formclass(obj=self.document)

    def validate(self):
        """Validate self.form, assuming Flask-WTF Form"""
        return self.form.validate_on_submit()


class DocumentWorkflow(docflow.DocumentWorkflow):
    __doc__ = docflow.DocumentWorkflow.__doc__

    exception_state = WorkflowStateException

    def permissions(self):
        """
        Permissions for this workflow. Plays nice with
        :meth:`coaster.views.load_models` and
        :class:`coaster.sqlalchemy.PermissionMixin` to determine the available
        permissions to the current user.
        """
        perms = set(super(DocumentWorkflow, self).permissions())
        if g:
            if hasattr(g, 'permissions'):
                perms.update(g.permissions or [])
            if hasattr(self.document, 'permissions'):
                perms = self.document.permissions(current_auth.actor, perms)
        return perms
