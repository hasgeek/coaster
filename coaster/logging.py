# -*- coding: utf-8 -*-

from __future__ import absolute_import
import logging.handlers
import cStringIO
import traceback


class LocalVarFormatter(logging.Formatter):
    def formatException(self, ei):
        tb = ei[2]
        while 1:
            if not tb.tb_next:
                break
            tb = tb.tb_next
        stack = []
        f = tb.tb_frame
        while f:
            stack.append(f)
            f = f.f_back
        stack.reverse()

        sio = cStringIO.StringIO()
        traceback.print_exception(ei[0], ei[1], ei[2], None, sio)

        for frame in stack:
            print >> sio
            print >> sio, "Frame %s in %s at line %s" % (frame.f_code.co_name,
                                                         frame.f_code.co_filename,
                                                         frame.f_lineno)
            for key, value in frame.f_locals.items():
                print >> sio, "\t%20s = " % key,
                try:
                    print >> sio, repr(value)
                except:
                    print >> sio, "<ERROR WHILE PRINTING VALUE>"

        s = sio.getvalue()
        sio.close()
        if s[-1:] == "\n":
            s = s[:-1]
        return s


def configure(app):
    formatter = LocalVarFormatter()

    file_handler = logging.FileHandler(app.config.get('LOGFILE', 'error.log'))
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.WARNING)
    app.logger.addHandler(file_handler)
    if app.config.get('ADMINS'):
        mail_sender = app.config.get('DEFAULT_MAIL_SENDER', 'logs@example.com')
        if isinstance(mail_sender, (list, tuple)):
            mail_sender = mail_sender[1]  # Get email from (name, email)
        if app.config.get('MAIL_USERNAME') and app.config.get('MAIL_PASSWORD'):
            credentials = (app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
        else:
            credentials = None
        mail_handler = logging.handlers.SMTPHandler(app.config.get('MAIL_SERVER', 'localhost'),
            mail_sender,
            app.config['ADMINS'],
            '%s failure' % app.name,
            credentials=credentials)
        mail_handler.setFormatter(formatter)
        mail_handler.setLevel(logging.ERROR)
        app.logger.addHandler(mail_handler)
