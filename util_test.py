# coding=utf-8
"""Unit tests for util.py.
"""


from appengine_config import HTTP_TIMEOUT
from testutil import FakeAuthEntity, FakeSource
from webmentiontools import send

import json
import testutil
import urllib
import urlparse
import util
import webapp2

# the invisible character in the middle is an unusual unicode character
UNICODE_STR = u'a ✁ b'


class UtilTest(testutil.ModelsTest):

  def test_follow_redirects(self):
    self.expect_requests_head('http://will/redirect',
                              redirected_url='http://final/url')
    self.mox.ReplayAll()
    self.assert_equals('http://final/url',
                       util.follow_redirects('http://will/redirect').url)

    # the result should now be in memcache, so we shouldn't fetch the URL again
    self.assert_equals('http://final/url',
                       util.follow_redirects('http://will/redirect').url)


  def test_follow_redirects_with_refresh_header(self):
    self.expect_requests_head('http://will/redirect',
                              response_headers={'refresh': '0; url=http://refresh'})
    self.expect_requests_head('http://refresh', redirected_url='http://final')

    self.mox.ReplayAll()
    self.assert_equals('http://final',
                       util.follow_redirects('http://will/redirect').url)

  def test_follow_redirects_defaults_scheme_to_http(self):
    self.expect_requests_head('http://foo/bar', redirected_url='http://final')
    self.mox.ReplayAll()
    self.assert_equals('http://final', util.follow_redirects('foo/bar').url)

  def test_maybe_add_or_delete_source(self):
    # profile url with valid domain is required for publish
    for bad_url in None, 'not>a<url', 'http://fa.ke/xyz':
      auth_entity = FakeAuthEntity(id='x', user_json=json.dumps({'url': bad_url}))
      auth_entity.put()
      self.assertIsNone(self.handler.maybe_add_or_delete_source(
        FakeSource, auth_entity,
        self.handler.construct_state_param_for_add(feature='publish')))

    auth_entity = FakeAuthEntity(id='x', user_json=json.dumps(
        {'url': 'http://foo.com/', 'name': UNICODE_STR}))
    auth_entity.put()
    src = self.handler.maybe_add_or_delete_source(
      FakeSource, auth_entity,
      self.handler.construct_state_param_for_add(feature='publish'))
    self.assertEquals(['publish'], src.features)

    self.assertEquals(302, self.handler.response.status_int)
    parsed = urlparse.urlparse(self.handler.response.headers['Location'])
    self.assertIn(UNICODE_STR, urllib.unquote_plus(parsed.fragment).decode('utf-8'))

    for feature in None, '':
      src = self.handler.maybe_add_or_delete_source(
        FakeSource, auth_entity,
        self.handler.construct_state_param_for_add(feature))
      self.assertEquals([], src.features)

  def test_prune_activity(self):
    for orig, expected in (
      ({'id': 1, 'content': 'X', 'foo': 'bar'}, {'id': 1, 'content': 'X'}),
      ({'id': 1, 'object': {'objectType': 'note'}}, {'id': 1}),
      ({'id': 1, 'object': {'url': 'http://xyz'}},) * 2,  # no change
      ({'to': [{'objectType': 'group', 'alias': '@public'}]}, {}),
      ({'object': {'to': [{'objectType': 'group', 'alias': '@private'}]}},) * 2,
      ({'id': 1, 'object': {'id': 1}}, {'id': 1}),
      ({'id': 1, 'object': {'id': 2}},) * 2,
      ):
      self.assert_equals(expected, util.prune_activity(orig))

  def test_webmention_tools_relative_webmention_endpoint_in_body(self):
    super(testutil.HandlerTest, self).expect_requests_get('http://target/', """
<html><meta>
<link rel="webmention" href="/endpoint">
</meta></html>""", verify=False)
    self.mox.ReplayAll()

    mention = send.WebmentionSend('http://source/', 'http://target/')
    mention.requests_kwargs = {'timeout': HTTP_TIMEOUT}
    mention._discoverEndpoint()
    self.assertEquals('http://target/endpoint', mention.receiver_endpoint)

  def test_webmention_tools_relative_webmention_endpoint_in_header(self):
    super(testutil.HandlerTest, self).expect_requests_get(
      'http://target/', '', verify=False,
      response_headers={'Link': '</endpoint>; rel="webmention"'})
    self.mox.ReplayAll()

    mention = send.WebmentionSend('http://source/', 'http://target/')
    mention.requests_kwargs = {'timeout': HTTP_TIMEOUT}
    mention._discoverEndpoint()
    self.assertEquals('http://target/endpoint', mention.receiver_endpoint)

  def test_clean_webmention_url(self):
    cwt = util.clean_webmention_url
    for unchanged in 'http://foo', 'http://foo#bar', 'http://foo?x=y&z=w':
      self.assertEquals(unchanged, cwt(unchanged))

    self.assertEquals('http://foo', cwt('http://foo?utm_source=x&utm_campaign=y'))
    self.assertEquals('http://foo?a=b&c=d', cwt('http://foo?a=b&utm_source=x&c=d'))

  def test_get_webmention_target_blacklisted_urls(self):
    for bad in ('http://facebook.com/x', 'https://www.facebook.com/y',
                'http://sub.dom.ain.facebook.com/z'):
      self.assertFalse(util.get_webmention_target(bad)[2], bad)

    self.assertTrue(util.get_webmention_target('http://good.com/a')[2])

  def test_get_webmention_cleans_redirected_urls(self):
    self.expect_requests_head('http://foo/bar',
                              redirected_url='http://final?utm_source=x')
    self.mox.ReplayAll()
    self.assert_equals(('http://final', 'final', True),
                       util.get_webmention_target('http://foo/bar'))

  def test_registration_callback(self):
    """Run through an authorization back and forth and make sure that
    the external callback makes it all the way through.
    """
    encoded_state = urllib.quote_plus(
      '{"callback":"http://withknown.com/bridgy_callback",'
      '"feature":"listen","operation":"add"}')

    application = webapp2.WSGIApplication([
      ('/fakesource/start', testutil.FakeStartHandler),
      ('/fakesource/add', testutil.FakeAddHandler),
    ])

    self.expect_requests_get(
      u'http://fakeuser.com/',
      response='<html><link rel="webmention" href="/webmention"></html>',
      verify=False)

    self.mox.ReplayAll()

    resp = application.get_response(
      '/fakesource/start', method='POST', body=urllib.urlencode({
        'feature': 'listen',
        'callback': 'http://withknown.com/bridgy_callback',
      }))

    self.assert_equals(302, resp.status_code)
    self.assert_equals('http://fake/auth/url', resp.headers['location'])

    resp = application.get_response(
      '/fakesource/add?state=' + encoded_state +
      '&oauth_token=fake-token&oauth_token_secret=fake-secret')

    self.assert_equals(302, resp.status_code)
    self.assert_equals(
      'http://withknown.com/bridgy_callback?result=success&user=0123456789',
      resp.headers['location'])

    source = FakeSource.get_by_id('0123456789')
    self.assertTrue(source)
    self.assert_equals('Fake User', source.name)
    self.assert_equals(['listen'], source.features)

  def test_registration_with_user_url(self):
    """Run through an authorization back and forth with a custom user url
    provided to the auth mechanism
    """
    encoded_state = urllib.quote_plus(
      '{"callback":"http://withknown.com/bridgy_callback","feature":"listen",'
      '"operation":"add","user_url":"https://kylewm.com"}')

    application = webapp2.WSGIApplication([
      ('/fakesource/start', testutil.FakeStartHandler),
      ('/fakesource/add', testutil.FakeAddHandler),
    ])

    self.expect_requests_get(
      'https://kylewm.com',
      response='<html><link rel="webmention" href="/webmention"></html>',
      verify=False)

    self.mox.ReplayAll()

    resp = application.get_response(
      '/fakesource/start', method='POST', body=urllib.urlencode({
        'feature': 'listen',
        'callback': 'http://withknown.com/bridgy_callback',
        'user_url': 'https://kylewm.com',
      }))

    self.assert_equals(302, resp.status_code)
    self.assert_equals('http://fake/auth/url', resp.headers['location'])

    resp = application.get_response(
      '/fakesource/add?state=' + encoded_state +
      '&oauth_token=fake-token&oauth_token_secret=fake-secret')

    self.assert_equals(302, resp.status_code)
    self.assert_equals(
      'http://withknown.com/bridgy_callback?result=success&user=0123456789',
      resp.headers['location'])

    source = FakeSource.get_by_id('0123456789')
    self.assertTrue(source)
    self.assert_equals('Fake User', source.name)
    self.assert_equals(['listen'], source.features)
    self.assert_equals(['https://kylewm.com', 'http://fakeuser.com/'],
                       source.domain_urls)
    self.assert_equals(['kylewm.com', 'fakeuser.com'], source.domains)

  def test_registration_decline(self):
    """Run through an authorization back and forth in the case of a
    decline and make sure that the callback makes it all the way
    through.
    """
    encoded_state = urllib.quote_plus(
      '{"callback":"http://withknown.com/bridgy_callback",'
      '"feature":"listen","operation":"add"}')

    application = webapp2.WSGIApplication([
      ('/fakesource/start', testutil.FakeStartHandler),
      ('/fakesource/add', testutil.FakeAddHandler.with_auth(None)),
    ])

    self.mox.ReplayAll()

    resp = application.get_response(
      '/fakesource/start', method='POST', body=urllib.urlencode({
        'feature': 'publish',
        'callback': 'http://withknown.com/bridgy_callback',
      }))
    self.assert_equals(302, resp.status_code)
    self.assert_equals('http://fake/auth/url', resp.headers['location'])

    resp = application.get_response(
      '/fakesource/add?state=%s&denied=1' % encoded_state)
    self.assert_equals(302, resp.status_code)
    self.assert_equals('http://withknown.com/bridgy_callback?result=declined',
                       resp.headers['location'])
