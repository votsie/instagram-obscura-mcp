import unittest

from instagram_mcp.auth import filter_instagram_state, login_status


class AuthStateTests(unittest.TestCase):
    def test_state_is_limited_to_instagram_and_keeps_cookie_flags(self):
        state = {'cookies': [
            {'name': 'sessionid', 'value': 'secret', 'domain': '.instagram.com', 'path': '/',
             'secure': True, 'httpOnly': True, 'sameSite': 'None', 'expires': -1},
            {'name': 'other', 'value': 'bad', 'domain': '.facebook.com', 'path': '/'},
            {'name': 'spoof', 'value': 'bad', 'domain': '.instagram.com.evil.test', 'path': '/'},
        ], 'origins': [{'origin': 'https://www.instagram.com', 'localStorage': [{'name': 'a', 'value': 'b'}]},
                       {'origin': 'https://facebook.com', 'localStorage': [{'name': 'bad', 'value': 'bad'}]}]}
        result = filter_instagram_state(state, {'temporary': 'value'})
        self.assertEqual([item['name'] for item in result['cookies']], ['sessionid'])
        self.assertEqual(result['cookies'][0]['httpOnly'], True)
        self.assertNotIn('expires', result['cookies'][0])
        self.assertEqual(list(result['local_storage']), ['https://www.instagram.com'])
        self.assertEqual(result['session_storage'], {'temporary': 'value'})

    def test_cookie_alone_on_login_screen_is_not_success(self):
        cookies = [{'name': 'sessionid', 'value': 'secret', 'domain': '.instagram.com'}]
        self.assertFalse(login_status(cookies, 'https://www.instagram.com/accounts/login/')['authenticated'])
        self.assertTrue(login_status(cookies, 'https://www.instagram.com/')['authenticated'])
        self.assertTrue(login_status(cookies, 'https://www.instagram.com/accounts/onetap/')['authenticated'])
        self.assertFalse(login_status(cookies, 'https://www.instagram.com/accounts/two_factor/')['authenticated'])
        self.assertFalse(login_status([], 'https://www.instagram.com/')['authenticated'])

    def test_no_state_values_in_returned_status(self):
        result = login_status([{'name': 'sessionid', 'value': 'secret', 'domain': '.instagram.com'}],
                              'https://www.instagram.com/')
        self.assertNotIn('secret', repr(result))


if __name__ == '__main__':
    unittest.main()
