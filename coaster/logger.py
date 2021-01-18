"""
Logger
=======

Coaster can help your application log errors at run-time. Initialize with
:func:`coaster.logger.init_app`. If you use :func:`coaster.app.init_app`,
this is done automatically for you.
"""

from datetime import datetime, timedelta
from io import StringIO
from pprint import pprint
from typing import Dict
import logging.handlers
import re
import traceback

from flask import escape, g, request, session

import requests

from .auth import current_auth

_card_re = re.compile(r'\b(?:\d[ -]*?){13,16}\b')
# These keywords are borrowed from Sentry's documentation and expanded for PII
_filter_re = re.compile(
    '''
    (password
    |secret
    |passwd
    |api_key
    |apikey
    |access_token
    |auth_token
    |_token
    |token_
    |credentials
    |mysql_pwd
    |stripetoken
    |cardnumber
    |email
    |phone)
    ''',
    re.I | re.X,
)

# global var as lazy in-memory cache
error_throttle_timestamp_sms: Dict[str, datetime] = {}
error_throttle_timestamp_slack: Dict[str, datetime] = {}
error_throttle_timestamp_telegram: Dict[str, datetime] = {}


class FilteredValueIndicator:
    def __str__(self):
        return '[Filtered]'

    def __repr__(self):
        return '[Filtered]'


# Construct a singleton
filtered_value_indicator = FilteredValueIndicator()


def filtered_value(key, value):
    if isinstance(key, str) and _filter_re.search(key):
        return filtered_value_indicator
    elif isinstance(value, str):
        return _card_re.sub('[Filtered]', value)
    return value


def pprint_with_indent(dictlike, outfile, indent=4):
    """Filter values and pprint with indent to create a Markdown code block."""
    out = StringIO()
    pprint(  # NOQA: T003
        {key: filtered_value(key, value) for key, value in dictlike.items()}, out
    )
    # textwrap.indent would have been simpler but is not present in Python 2.7
    outfile.write(
        '\n'.join((' ' * indent) + line for line in out.getvalue().split('\n'))
    )
    out.close()


class LocalVarFormatter(logging.Formatter):
    """
    Custom log formatter that logs the contents of local variables in the stack frame.
    """

    def format(self, record):  # NOQA: A003
        """
        Format the specified record as text. Overrides
        :meth:`logging.Formatter.format` to remove cache of
        :attr:`record.exc_text` unless it was produced by this formatter.
        """
        if record.exc_info:
            if record.exc_text:
                if "Stack frames (most recent call first)" not in record.exc_text:
                    record.exc_text = None
        return super(LocalVarFormatter, self).format(record)

    def formatException(self, ei):  # NOQA: N802
        tb = ei[2]
        while True:
            if not tb.tb_next:
                break
            tb = tb.tb_next
        stack = []
        f = tb.tb_frame
        while f:
            stack.append(f)
            f = f.f_back

        sio = StringIO()
        traceback.print_exception(ei[0], ei[1], ei[2], None, sio)

        print('\n----------\n', file=sio)  # NOQA: T001
        # XXX: The following text is used as a signature in :meth:`format` above
        print("Stack frames (most recent call first):", file=sio)  # NOQA: T001
        for frame in stack:
            print('\n----\n', file=sio)  # NOQA: T001
            print(  # NOQA: T001
                "Frame %s in %s at line %s"
                % (frame.f_code.co_name, frame.f_code.co_filename, frame.f_lineno),
                file=sio,
            )
            for key, value in list(frame.f_locals.items()):
                print("\t%20s = " % key, end=' ', file=sio)  # NOQA: T001
                try:
                    print(repr(filtered_value(key, value)), file=sio)  # NOQA: T001
                except:  # NOQA
                    # We need a bare except clause because this is the exception
                    # handler. It can't have exceptions of its own.
                    print("<ERROR WHILE PRINTING VALUE>", file=sio)  # NOQA: T001

        if request:
            print('\n----------\n', file=sio)  # NOQA: T001
            print("Request context:", file=sio)  # NOQA: T001
            request_data = {
                'form': request.form,
                'args': request.args,
                'cookies': request.cookies,
                'stream': request.stream,
                'headers': request.headers,
                'data': request.data,
                'files': request.files,
                'environ': request.environ,
                'method': request.method,
                'blueprint': request.blueprint,
                'endpoint': request.endpoint,
                'view_args': request.view_args,
            }
            try:
                pprint_with_indent(request_data, sio)
            except:  # NOQA
                print("<ERROR WHILE PRINTING VALUE>", file=sio)  # NOQA: T001

        if session:
            print('\n----------\n', file=sio)  # NOQA: T001
            print("Session cookie contents:", file=sio)  # NOQA: T001
            try:
                pprint_with_indent(session, sio)
            except:  # NOQA
                print("<ERROR WHILE PRINTING VALUE>", file=sio)  # NOQA: T001

        if g:
            print('\n----------\n', file=sio)  # NOQA: T001
            print("App context:", file=sio)  # NOQA: T001
            try:
                pprint_with_indent(vars(g), sio)
            except:  # NOQA
                print("<ERROR WHILE PRINTING VALUE>", file=sio)  # NOQA: T001

        if current_auth:
            print('\n----------\n', file=sio)  # NOQA: T001
            print("Current auth:", file=sio)  # NOQA: T001
            try:
                pprint_with_indent(vars(current_auth), sio)
            except:  # NOQA
                print("<ERROR WHILE PRINTING VALUE>", file=sio)  # NOQA: T001

        s = sio.getvalue()
        sio.close()
        if s[-1:] == '\n':
            s = s[:-1]
        return s


class SMSHandler(logging.Handler):
    """
    Custom logging handler to send SMSes to admins
    """

    def __init__(
        self,
        app_name,
        exotel_sid,
        exotel_token,
        exotel_from,
        twilio_sid,
        twilio_token,
        twilio_from,
        phonenumbers,
    ):
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
        throttle_key = (record.module, record.lineno)
        if throttle_key not in error_throttle_timestamp_sms or (
            (datetime.utcnow() - error_throttle_timestamp_sms[throttle_key])
            > timedelta(minutes=5)
        ):
            msg = "{message}: {info}".format(
                message=record.message,
                info=repr(record.exc_info[1]) if record.exc_info else '',
            )
            for phonenumber in self.phonenumbers:
                self.sendsms(
                    phonenumber,
                    "Error in {name}. {msg}. "
                    "Please check your email for details".format(
                        name=self.app_name, msg=msg
                    ),
                )
            error_throttle_timestamp_sms[throttle_key] = datetime.utcnow()

    def sendsms(self, number, message):
        try:
            if number.startswith('+91'):  # Indian
                requests.post(
                    'https://twilix.exotel.in/v1/Accounts/{sid}/Sms/send.json'.format(
                        sid=self.exotel_sid
                    ),
                    auth=(self.exotel_sid, self.exotel_token),
                    data={'From': self.exotel_from, 'To': number, 'Body': message},
                )
            else:
                requests.post(
                    'https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json'.format(
                        sid=self.twilio_sid
                    ),
                    auth=(self.twilio_sid, self.twilio_token),
                    data={'From': self.twilio_from, 'To': number, 'Body': message},
                )
        except:  # NOQA  # nosec
            # We need a bare except clause because this is the exception handler.
            # It can't have exceptions of its own.
            pass


class SlackHandler(logging.Handler):
    """
    Custom logging handler to post error reports to Slack.
    """

    def __init__(self, app_name, webhooks):
        super(SlackHandler, self).__init__()
        self.app_name = app_name
        self.webhooks = webhooks

    def emit(self, record):
        throttle_key = (record.module, record.lineno)
        if throttle_key not in error_throttle_timestamp_slack or (
            (datetime.utcnow() - error_throttle_timestamp_slack[throttle_key])
            > timedelta(minutes=5)
        ):

            # Sanity check:
            # If we're not going to be reporting this, don't bother to format payload
            if record.levelname not in [
                lname
                for webhook in self.webhooks
                for lname in webhook.get('levelnames', [])
            ]:
                return
            if record.exc_text:
                double_split = [
                    s.split('----') for s in record.exc_text.split('----------')
                ]
                flat_list = [item for sublist in double_split for item in sublist]
                # Separate out the first line of each section. It'll be used as the
                # "pretext" while the rest will be used as a "text" attachment.
                sections = [s.strip().split('\n', 1) for s in flat_list]
            else:
                sections = []

            data = {
                'text': "*{levelname}* in {name}: {message}: `{info}`".format(
                    levelname=record.levelname,
                    name=self.app_name,
                    message=record.message,
                    info=repr(record.exc_info[1]) if record.exc_info else '',
                ),
                'attachments': [
                    {
                        'mrkdwn_in': ['text'],
                        'fallback': section[0],
                        'pretext': section[0],
                        'text': ('```\n' + section[1] + '\n```')
                        if len(section) > 1
                        else '',
                    }
                    for section in sections
                ],
            }

            for webhook in self.webhooks:
                if record.levelname not in webhook.get('levelnames', []):
                    continue
                payload = dict(data)
                for attr in ('channel', 'username', 'icon_emoji'):
                    if attr in webhook:
                        payload[attr] = webhook[attr]

                try:
                    requests.post(
                        webhook['url'],
                        json=payload,
                        headers={'Content-Type': 'application/json'},
                    )
                except:  # NOQA  # nosec
                    # We need a bare except clause because this is the exception
                    # handler. It can't have exceptions of its own.
                    pass
                error_throttle_timestamp_slack[throttle_key] = datetime.utcnow()


class TelegramHandler(logging.Handler):
    """
    Custom logging handler to report errors to a Telegram chat
    """

    def __init__(self, app_name, chatid, apikey):
        super(TelegramHandler, self).__init__()
        self.app_name = app_name
        self.chatid = chatid
        self.apikey = apikey

    def emit(self, record):
        throttle_key = (record.module, record.lineno)
        if throttle_key not in error_throttle_timestamp_telegram or (
            (datetime.utcnow() - error_throttle_timestamp_telegram[throttle_key])
            > timedelta(minutes=5)
        ):
            text = '<b>{levelname}</b> in <b>{name}</b>: {message}'.format(
                levelname=escape(record.levelname),
                name=escape(self.app_name),
                message=escape(record.message),
            )
            if record.exc_info:
                text += '\n\n<pre>{traceback}</pre>'.format(
                    traceback=escape(
                        ''.join(traceback.format_exception(*record.exc_info))
                    )
                )
            if len(text) > 4096:
                text = text[: (4096 - 7)] + '…</pre>'
            requests.post(
                'https://api.telegram.org/bot{apikey}/sendMessage'.format(
                    apikey=self.apikey
                ),
                data={
                    'chat_id': self.chatid,
                    'parse_mode': 'html',
                    'text': text,
                    'disable_preview': True,
                },
            )
            error_throttle_timestamp_telegram[throttle_key] = datetime.utcnow()


def init_app(app):
    """
    Enables logging for an app using :class:`LocalVarFormatter`. Requires the
    app to be configured and checks for the following configuration parameters.
    All are optional:

    * ``LOGFILE``: Name of the file to log to (default ``error.log``)
    * ``LOGFILE_LEVEL``: Logging level to use for file logger (default `WARNING`)
    * ``ADMINS``: List of email addresses of admins who will be mailed error reports
    * ``MAIL_DEFAULT_SENDER``: From address of email. Can be an address or a tuple with
        name and address
    * ``MAIL_SERVER``: SMTP server to send with (default ``localhost``)
    * ``MAIL_USERNAME`` and ``MAIL_PASSWORD``: SMTP credentials, if required
    * ``SLACK_LOGGING_WEBHOOKS``: If present, will send error logs to all specified
        Slack webhooks
    * ``ADMIN_NUMBERS``: List of mobile numbers of admin to send SMS alerts. Requires
        the following values too
    * ``SMS_EXOTEL_SID``: Exotel SID for Indian numbers (+91 prefix)
    * ``SMS_EXOTEL_TOKEN``: Exotel token
    * ``SMS_EXOTEL_FROM``: Exotel sender's number
    * ``SMS_TWILIO_SID``: Twilio SID for non-Indian numbers
    * ``SMS_TWILIO_TOKEN``: Twilio token
    * ``SMS_TWILIO_FROM``: Twilio sender's number

    Format for ``SLACK_LOGGING_WEBHOOKS``::

        SLACK_LOGGING_WEBHOOKS = [{
            'levelnames': ['WARNING', 'ERROR', 'CRITICAL'],
            'url': 'https://hooks.slack.com/...'
            }]

    """
    if not app.debug:
        # Downgrade from default WARNING level to INFO
        app.logger.setLevel(logging.INFO)

    formatter = LocalVarFormatter(
        '%(asctime)s - %(module)s.%(funcName)s:%(lineno)s - %(levelname)s - %(message)s'
    )

    error_log_file = app.config.get('LOGFILE', 'error.log')
    if error_log_file:  # Specify a falsy value in config to disable the log file
        file_handler = logging.handlers.TimedRotatingFileHandler(
            error_log_file,
            when=app.config.get('LOGFILE_WHEN', 'midnight'),
            backupCount=app.config.get('LOGFILE_BACKUPCOUNT', 0),
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(app.config.get('LOGFILE_LEVEL', logging.WARNING))
        app.logger.addHandler(file_handler)

    if app.config.get('ADMIN_NUMBERS'):
        if all(
            key in app.config
            for key in [
                'SMS_EXOTEL_SID',
                'SMS_EXOTEL_TOKEN',
                'SMS_EXOTEL_FROM',
                'SMS_TWILIO_SID',
                'SMS_TWILIO_TOKEN',
                'SMS_TWILIO_FROM',
            ]
        ):

            # A little trickery because directly creating
            # an SMSHandler object didn't work
            logging.handlers.SMSHandler = SMSHandler

            sms_handler = logging.handlers.SMSHandler(
                app_name=app.config.get('SITE_ID') or app.name,
                exotel_sid=app.config['SMS_EXOTEL_SID'],
                exotel_token=app.config['SMS_EXOTEL_TOKEN'],
                exotel_from=app.config['SMS_EXOTEL_FROM'],
                twilio_sid=app.config['SMS_TWILIO_SID'],
                twilio_token=app.config['SMS_TWILIO_TOKEN'],
                twilio_from=app.config['SMS_TWILIO_FROM'],
                phonenumbers=app.config['ADMIN_NUMBERS'],
            )
            sms_handler.setLevel(logging.ERROR)
            app.logger.addHandler(sms_handler)

    if app.config.get('SLACK_LOGGING_WEBHOOKS'):
        logging.handlers.SlackHandler = SlackHandler
        slack_handler = logging.handlers.SlackHandler(
            app_name=app.config.get('SITE_ID') or app.name,
            webhooks=app.config['SLACK_LOGGING_WEBHOOKS'],
        )
        slack_handler.setFormatter(formatter)
        slack_handler.setLevel(logging.NOTSET)
        app.logger.addHandler(slack_handler)

    if app.config.get('TELEGRAM_ERROR_CHATID') and app.config.get(
        'TELEGRAM_ERROR_APIKEY'
    ):
        logging.handlers.TelegramHandler = TelegramHandler
        telegram_handler = logging.handlers.TelegramHandler(
            app_name=app.config.get('SITE_ID') or app.name,
            chatid=app.config['TELEGRAM_ERROR_CHATID'],
            apikey=app.config['TELEGRAM_ERROR_APIKEY'],
        )
        telegram_handler.setLevel(logging.ERROR)
        app.logger.addHandler(telegram_handler)

    if app.config.get('ADMINS'):
        # MAIL_DEFAULT_SENDER is the new setting for default mail sender in Flask-Mail
        # DEFAULT_MAIL_SENDER is the old setting. We look for both
        mail_sender = app.config.get('MAIL_DEFAULT_SENDER') or app.config.get(
            'DEFAULT_MAIL_SENDER', 'logs@example.com'
        )
        if isinstance(mail_sender, (list, tuple)):
            mail_sender = mail_sender[1]  # Get email from (name, email)
        if app.config.get('MAIL_USERNAME') and app.config.get('MAIL_PASSWORD'):
            credentials = (app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
        else:
            credentials = None
        mail_handler = logging.handlers.SMTPHandler(
            app.config.get('MAIL_SERVER', 'localhost'),
            mail_sender,
            app.config['ADMINS'],
            '%s failure' % (app.config.get('SITE_ID') or app.name),
            credentials=credentials,
        )
        mail_handler.setFormatter(formatter)
        mail_handler.setLevel(logging.ERROR)
        app.logger.addHandler(mail_handler)


# Legacy name
configure = init_app
