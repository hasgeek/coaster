# -*- coding: utf-8 -*-

from __future__ import absolute_import
from datetime import timedelta, datetime
import logging.handlers
import cStringIO
import traceback
import requests

# global var as lazy in-memory cache
error_throttle_timestamp = {
    'funcName': '',
    'lineno': '',
    'timestamp': datetime(2003, 8, 4, 12, 30, 45)  # A long, long time ago... I can still remember. How that music used to make me smile.
}


class LocalVarFormatter(logging.Formatter):
    """
    Custom log formatter that logs the contents of local variables in the stack frame.
    """
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


class SMSHandler(logging.Handler):
    """
    Custom logging handler to send SMSes to admins
    """
    def __init__(self, app_name, exotel_sid, exotel_token, exotel_from, twilio_sid, twilio_token, twilio_from, phonenumbers):
            logging.Handler.__init__(self)
            self.app_name = app_name
            self.phonenumbers = phonenumbers
            self.exotel_sid = exotel_sid
            self.exotel_token = exotel_token
            self.exotel_from = exotel_from
            self.twilio_sid = twilio_sid
            self.twilio_token = twilio_token
            self.twilio_from = twilio_from

    def emit(self, record):
        if(record.funcName != error_throttle_timestamp['funcName'] or record.lineno != error_throttle_timestamp['lineno'] or (datetime.now() - error_throttle_timestamp['timestamp']) > timedelta(minutes=5)):
            for phonenumber in self.phonenumbers:
                self.sendsms(phonenumber, 'Error in {name}. Please check your email for details'.format(name=self.app_name))
            error_throttle_timestamp['funcName'] = record.funcName
            error_throttle_timestamp['lineno'] = record.lineno
            error_throttle_timestamp['timestamp'] = datetime.now()

    def sendsms(self, number, message):
        try:
            if number.startswith('+91'):  # Indian
                requests.post('https://twilix.exotel.in/v1/Accounts/{sid}/Sms/send.json'.format(sid=self.exotel_sid),
                        auth=(self.exotel_sid, self.exotel_token),
                        data={
                            'From': self.exotel_from,
                            'To': number,
                            'Body': message
                        })
            else:
                requests.post('https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json'.format(sid=self.twilio_sid),
                        auth=(self.twilio_sid, self.twilio_token),
                        data={
                            'From': self.twilio_from,
                            'To': number,
                            'Body': message
                        })
        except:
            pass


def init_app(app):
    """
    Enables logging for an app using :class:`LocalVarFormatter`.

    This function requires an app that has already been configured
    (perhaps using :func:`coaster.app.init_app`). It checks for the following
    configuration parameters:

    * ``LOGFILE``: Name of the file to log to (default ``error.log``)
    * ``ADMINS``: List of email addresses of admins who will be mailed error reports
    * ``MAIL_DEFAULT_SENDER``: From address of email. Can be an address or a tuple with name and address
    * ``MAIL_SERVER``: SMTP server to send with (default ``localhost``)
    * ``MAIL_USERNAME`` and ``MAIL_PASSWORD``: SMTP credentials, if required
    * ``FLUENTD_SERVER``: If specified, will enable logging to fluentd
    """
    formatter = LocalVarFormatter()

    file_handler = logging.FileHandler(app.config.get('LOGFILE', 'error.log'))
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.WARNING)
    app.logger.addHandler(file_handler)

    if app.config.get('ADMIN_NUMBERS'):
        if (app.config.get('SMS_EXOTEL_SID') and app.config.get('SMS_EXOTEL_TOKEN') and app.config.get('SMS_EXOTEL_FROM') and app.config.get('SMS_TWILIO_SID') and app.config.get('SMS_TWILIO_TOKEN') and app.config.get('SMS_TWILIO_FROM')):
            exotel_sid = app.config['SMS_EXOTEL_SID']
            exotel_token = app.config['SMS_EXOTEL_TOKEN']
            exotel_from = app.config['SMS_EXOTEL_FROM']
            twilio_sid = app.config['SMS_TWILIO_SID']
            twilio_token = app.config['SMS_TWILIO_TOKEN']
            twilio_from = app.config['SMS_TWILIO_FROM']

            # A little trickery because directly creating
            # an SMSHandler object didn't work
            logging.handlers.SMSHandler = SMSHandler

            sms_handler = logging.handlers.SMSHandler(app_name=app.name, exotel_sid=exotel_sid, exotel_token=exotel_token, exotel_from=exotel_from, twilio_sid=twilio_sid, twilio_token=twilio_token, twilio_from=twilio_from, phonenumbers=app.config['ADMIN_NUMBERS'])
            sms_handler.setLevel(logging.ERROR)
            app.logger.addHandler(sms_handler)

    if app.config.get('ADMINS'):
        # MAIL_DEFAULT_SENDER is the new setting for default mail sender in Flask-Mail
        # DEFAULT_MAIL_SENDER is the old setting. We look for both
        mail_sender = app.config.get('MAIL_DEFAULT_SENDER') or app.config.get(
            'DEFAULT_MAIL_SENDER', 'logs@example.com')
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

configure = init_app
