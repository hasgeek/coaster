from io import StringIO

from coaster.logger import RepeatValueIndicator, filtered_value, pprint_with_indent


def test_filtered_value():
    """Test for filtered values."""
    # Doesn't touch normal key/value pairs
    assert filtered_value('normal', 'value') == 'value'
    assert filtered_value('also_normal', 123) == 123
    # But does redact sensitive keys
    assert filtered_value('password', '123pass') != '123pass'
    # The returned value is an object that renders via repr and str as '[Filtered]'
    assert repr(filtered_value('password', '123pass')) == '[Filtered]'
    assert str(filtered_value('password', '123pass')) == '[Filtered]'
    # Also works on partial matches in the keys
    assert repr(filtered_value('confirm_password', '123pass')) == '[Filtered]'
    # The filter uses a verbose regex. Words in the middle of the regex also work
    assert repr(filtered_value('access_token', 'secret-here')) == '[Filtered]'
    # Filters are case insensitive
    assert repr(filtered_value('TELEGRAM_ERROR_APIKEY', 'api:key')) == '[Filtered]'
    # Keys with 'token' as a word are also filtered
    assert repr(filtered_value('SMS_TWILIO_TOKEN', 'api:key')) == '[Filtered]'

    # Numbers that look like card numbers are filtered
    assert (
        filtered_value('anything', 'My number is 1234 5678 9012 3456')
        == 'My number is [Filtered]'
    )
    # This works with any combination of spaces and dashes within the number
    assert (
        filtered_value('anything', 'My number is 1234  5678-90123456')
        == 'My number is [Filtered]'
    )


def test_pprint_with_indent():
    """Test pprint_with_indent does indentation."""
    out = StringIO()
    data = {
        12: 34,
        'confirm_password': '12345qwerty',
        'credentials': ['abc', 'def'],
        'key': 'value',
        'nested_dict': {'password': 'not_filtered'},
        'password': '12345qwerty',
    }
    pprint_with_indent(data, out)
    assert (
        out.getvalue()
        == '''\
    {12: 34,
     'confirm_password': [Filtered],
     'credentials': [Filtered],
     'key': 'value',
     'nested_dict': {'password': 'not_filtered'},
     'password': [Filtered]}
'''
    )


def test_repeat_value_indicator():
    """Test RepeatValueIndicator class."""
    assert repr(RepeatValueIndicator('key')) == '<same as prior "key">'
    assert str(RepeatValueIndicator('key')) == '<same as prior "key">'
