"""
Logger
=======

Coaster can help your application log errors at run-time. Initialize with
:func:`coaster.logger.init_app`. If you use :func:`coaster.app.init_app`,
this is done automatically for you.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import textwrap
import traceback
import types
import typing as t
from datetime import datetime, timedelta
from html import escape
from io import StringIO
from pprint import pprint
from threading import Lock

if t.TYPE_CHECKING:
    from logging import _SysExcInfoType

import requests
from flask import Flask, g, request, session
from flask.config import Config

from .auth import current_auth

# Regex for credit card numbers
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
    re.IGNORECASE | re.VERBOSE,
)

# global var as lazy in-memory cache
error_throttle_timestamp_slack: t.Dict[t.Tuple[str, int], datetime] = {}
error_throttle_timestamp_telegram: t.Dict[t.Tuple[str, int], datetime] = {}


class FilteredValueIndicator:
    """Represent a filtered value."""

    def __str__(self) -> str:
        """Filter str."""
        return '[Filtered]'

    def __repr__(self) -> str:
        """Filter repr."""
        return '[Filtered]'


# Construct a singleton
filtered_value_indicator = FilteredValueIndicator()


class RepeatValueIndicator:
    """Represent a repeating value."""

    def __init__(self, key: str) -> None:
        """Init with key."""
        self.key = key

    def __repr__(self) -> str:
        """Return representation."""
        return f'<same as prior {self.key!r}>'

    __str__ = __repr__


def filtered_value(key: t.Any, value: t.Any) -> t.Any:
    """Find and mask sensitive values based on key names."""
    if isinstance(key, str) and _filter_re.search(key):
        return filtered_value_indicator
    if isinstance(value, str):
        return _card_re.sub('[Filtered]', value)
    return value


def pprint_with_indent(dictlike: t.Dict, outfile: t.IO, indent: int = 4) -> None:
    """Filter values and pprint with indent to create a Markdown code block."""
    out = StringIO()
    pprint(  # noqa: T203
        {key: filtered_value(key, value) for key, value in dictlike.items()}, out
    )
    outfile.write(textwrap.indent(out.getvalue(), ' ' * indent))
    out.close()


class LocalVarFormatter(logging.Formatter):
    """Log the contents of local variables in the stack frame."""

    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        """Init formatter."""
        super().__init__(*args, **kwargs)
        self.lock = Lock()

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        """
        Format the specified record as text.

        Overrides :meth:`logging.Formatter.format` to remove cache of
        :attr:`record.exc_text` unless it was produced by this formatter.
        """
        if (
            record.exc_info
            and record.exc_text
            and "Stack frames (most recent call first)" not in record.exc_text
        ):
            record.exc_text = None
        return super().format(record)

    def formatException(self, ei: _SysExcInfoType) -> str:  # noqa: N802
        """Render a stack trace with local variables in each stack frame."""
        tb = ei[2]
        if tb is None:
            return ''
        while True:
            if not tb.tb_next:
                break
            tb = tb.tb_next
        stack = []
        f: t.Optional[types.FrameType] = tb.tb_frame
        while f:
            stack.append(f)
            f = f.f_back

        sio = StringIO()
        traceback.print_exception(ei[0], ei[1], ei[2], None, sio)

        with self.lock:
            # Monkey-patch Flask Config's __repr__ to not dump sensitive config. This
            # can happen when a Jinja2 template is part of the stack, as templates get
            # app config. We perform this patch and dump within a lock to ensure no
            # conflict with a parallel stack dump -- which could otherwise restore the
            # original __repr__ while this is still dumping.
            original_config_repr = Config.__repr__
            Config.__repr__ = (  # type: ignore[method-assign]
                lambda self: '<Config [FILTERED]>'
            )
            value_cache: t.Dict[t.Any, str] = {}

            print('\n----------\n', file=sio)  # noqa: T201
            # XXX: The following text is used as a signature in :meth:`format` above
            print("Stack frames (most recent call first):", file=sio)  # noqa: T201
            for frame in stack:
                print('\n----\n', file=sio)  # noqa: T201
                print(  # noqa: T201
                    f"Frame {frame.f_code.co_name} in {frame.f_code.co_filename} at"
                    f" line {frame.f_lineno}",
                    file=sio,
                )
                for attr, value in list(frame.f_locals.items()):
                    idvalue = id(value)
                    if idvalue in value_cache:
                        value = RepeatValueIndicator(value_cache[idvalue])
                    else:
                        value_cache[idvalue] = f"{frame.f_code.co_name}.{attr}"
                    print(f"\t{attr:>20} = ", end=' ', file=sio)  # noqa: T201
                    try:
                        print(repr(filtered_value(attr, value)), file=sio)  # noqa: T201
                    except Exception:  # noqa: B902  # pylint: disable=broad-except
                        # We need a bare except clause because this is the exception
                        # handler. It can't have exceptions of its own.
                        print("<ERROR WHILE PRINTING VALUE>", file=sio)  # noqa: T201

            del value_cache
            Config.__repr__ = original_config_repr  # type: ignore[method-assign]

        if request:
            print('\n----------\n', file=sio)  # noqa: T201
            print("Request context:", file=sio)  # noqa: T201
            request_data = {
                'form': {
                    k: filtered_value(k, v)
                    for k, v in request.form.to_dict(flat=False).items()
                },
                'args': {
                    k: filtered_value(k, v)
                    for k, v in request.args.to_dict(flat=False).items()
                },
                'headers': request.headers,
                'environ': request.environ,
                'method': request.method,
                'blueprint': request.blueprint,
                'endpoint': request.endpoint,
                'view_args': request.view_args,
            }
            try:
                pprint_with_indent(request_data, sio)
            except Exception:  # noqa: B902  # pylint: disable=broad-except
                print("<ERROR WHILE PRINTING VALUE>", file=sio)  # noqa: T201

        if session:
            print('\n----------\n', file=sio)  # noqa: T201
            print("Session cookie contents:", file=sio)  # noqa: T201
            try:
                pprint_with_indent(dict(session), sio)
            except Exception:  # noqa: B902  # pylint: disable=broad-except
                print("<ERROR WHILE PRINTING VALUE>", file=sio)  # noqa: T201

        if g:
            print('\n----------\n', file=sio)  # noqa: T201
            print("App context:", file=sio)  # noqa: T201
            try:
                pprint_with_indent(vars(g), sio)
            except Exception:  # noqa: B902  # pylint: disable=broad-except
                print("<ERROR WHILE PRINTING VALUE>", file=sio)  # noqa: T201

        if current_auth:
            print('\n----------\n', file=sio)  # noqa: T201
            print("Current auth:", file=sio)  # noqa: T201
            try:
                pprint_with_indent(vars(current_auth), sio)
            except Exception:  # noqa: B902  # pylint: disable=broad-except
                print("<ERROR WHILE PRINTING VALUE>", file=sio)  # noqa: T201

        s = sio.getvalue()
        sio.close()
        if s[-1:] == '\n':
            s = s[:-1]
        return s


class SlackHandler(logging.Handler):
    """Custom logging handler to post error reports to Slack."""

    def __init__(self, app_name: str, webhooks: t.List[t.Dict[str, t.Any]]) -> None:
        """Init handler."""
        super().__init__()
        self.app_name = app_name
        self.webhooks = webhooks

    def emit(self, record: logging.LogRecord) -> None:
        """Emit an event."""
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
                # pylint: disable=consider-using-f-string
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
                        timeout=30,
                    )
                except Exception:  # nosec  # noqa: B902  # pylint: disable=broad-except
                    # We need a bare except clause because this is the exception
                    # handler. It can't have exceptions of its own.
                    pass
                error_throttle_timestamp_slack[throttle_key] = datetime.utcnow()


class TelegramHandler(logging.Handler):
    """Custom logging handler to report errors to a Telegram chat."""

    def __init__(
        self, app_name: str, chatid: str, apikey: str, threadid: t.Optional[str] = None
    ) -> None:
        """Init handler."""
        super().__init__()
        self.app_name = app_name
        self.chatid = chatid
        self.apikey = apikey
        self.threadid = threadid

    def emit(self, record: logging.LogRecord) -> None:
        """Emit an event."""
        throttle_key = (record.module, record.lineno)
        if throttle_key not in error_throttle_timestamp_telegram or (
            (datetime.utcnow() - error_throttle_timestamp_telegram[throttle_key])
            > timedelta(minutes=5)
        ):
            # pylint: disable=consider-using-f-string
            text = '<b>{levelname}</b> in <b>{name}</b>: {message}'.format(
                levelname=escape(record.levelname, False),
                name=escape(self.app_name, False),
                message=escape(record.message, False),
            )
            if record.exc_info:
                # Reverse the traceback, after dropping the first line with
                # "Traceback (most recent call first)".
                traceback_lines = traceback.format_exception(*record.exc_info)[1:][::-1]
                for index, stack_frame in enumerate(traceback_lines):
                    stack_frame_lines = stack_frame.split('\n', 1)
                    traceback_lines[index] = (
                        '\n'.join(
                            [escape(stack_frame_lines[0].strip(), False)]
                            + [
                                '<pre>' + escape(_l.strip(), False) + '</pre>'
                                for _l in stack_frame_lines[1:]
                                if _l
                            ]
                        )
                        + '\n'
                    )
                text += '\n\n' + '\n'.join(traceback_lines)
            if len(text) > 4096:
                text = text[: 4096 - 7]  # 7 = len('</pre>…')
                if text.count('<pre>') > text.count('</pre>'):
                    text += '</pre>'
                text += '…'

            telegram_post_data = {
                'chat_id': self.chatid,
                'parse_mode': 'html',
                'text': text,
                'disable_preview': True,
            }
            if self.threadid:
                telegram_post_data['message_thread_id'] = self.threadid
            requests.post(
                f'https://api.telegram.org/bot{self.apikey}/sendMessage',
                data=telegram_post_data,
                timeout=30,
            )
            error_throttle_timestamp_telegram[throttle_key] = datetime.utcnow()


def init_app(app: Flask) -> None:
    """
    Enable logging for an app using :class:`LocalVarFormatter`.

    Requires the app to be configured and checks for the following configuration
    parameters. All are optional:

    * ``LOGFILE``: Name of the file to log to (default ``error.log``)
    * ``LOGFILE_LEVEL``: Logging level to use for file logger (default `WARNING`)
    * ``ADMINS``: List of email addresses of admins who will be mailed error reports
    * ``MAIL_DEFAULT_SENDER``: From address of email. Can be an address or a tuple with
        name and address
    * ``MAIL_SERVER``: SMTP server to send with (default ``localhost``)
    * ``MAIL_USERNAME`` and ``MAIL_PASSWORD``: SMTP credentials, if required
    * ``SLACK_LOGGING_WEBHOOKS``: If present, will send error logs to all specified
        Slack webhooks
    * ``TELEGRAM_ERROR_CHATID`` and ``TELEGRAM_ERROR_APIKEY``: If present, will use the
        specified API key to post a message to the specified chat. If
        ``TELEGRAM_ERROR_THREADID`` is present, the message will be sent to the
        specified topic thread. ``TELEGRAM_ERROR_LEVEL`` may optionally specify the
        logging level, defaulting to :attr:`logging.ERROR`.

    Format for ``SLACK_LOGGING_WEBHOOKS``::

        SLACK_LOGGING_WEBHOOKS = [{
            'levelnames': ['WARNING', 'ERROR', 'CRITICAL'],
            'url': 'https://hooks.slack.com/...'
            }]

    """
    logger = app.logger  # logging.getLogger()

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
        logger.addHandler(file_handler)

    if app.config.get('SLACK_LOGGING_WEBHOOKS'):
        slack_handler = SlackHandler(
            app_name=app.config.get('SITE_ID') or app.name,
            webhooks=app.config['SLACK_LOGGING_WEBHOOKS'],
        )
        slack_handler.setFormatter(formatter)
        slack_handler.setLevel(logging.NOTSET)
        logger.addHandler(slack_handler)

    if app.config.get('TELEGRAM_ERROR_CHATID') and app.config.get(
        'TELEGRAM_ERROR_APIKEY'
    ):
        telegram_handler = TelegramHandler(
            app_name=app.config.get('SITE_ID') or app.name,
            chatid=app.config['TELEGRAM_ERROR_CHATID'],
            apikey=app.config['TELEGRAM_ERROR_APIKEY'],
            threadid=app.config.get('TELEGRAM_ERROR_THREADID'),
        )
        telegram_handler.setLevel(app.config.get('TELEGRAM_ERROR_LEVEL', logging.ERROR))
        logger.addHandler(telegram_handler)

    if app.config.get('ADMINS'):
        mail_sender = app.config.get('MAIL_DEFAULT_SENDER', 'logs@example.com')
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
            f"{app.config.get('SITE_ID') or app.name} failure",
            credentials=credentials,
        )
        mail_handler.setFormatter(formatter)
        mail_handler.setLevel(logging.ERROR)
        logger.addHandler(mail_handler)
