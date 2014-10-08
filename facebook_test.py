"""Unit tests for facebook.py.
"""

__author__ = ['Ryan Barrett <bridgy@ryanb.org>']

import copy
import json
import urllib
import urllib2

import appengine_config

import activitystreams
from activitystreams import facebook_test as as_facebook_test
from activitystreams.oauth_dropins import facebook as oauth_facebook
from facebook import FacebookPage
import facebook
import models
import testutil


class FacebookPageTest(testutil.ModelsTest):

  def setUp(self):
    super(FacebookPageTest, self).setUp()
    for config in (appengine_config, activitystreams.appengine_config,
                   activitystreams.oauth_dropins.appengine_config):
      setattr(config, 'FACEBOOK_APP_ID', 'my_app_id')
      setattr(config, 'FACEBOOK_APP_SECRET', 'my_app_secret')

    self.handler.messages = []
    self.auth_entity = oauth_facebook.FacebookAuth(
      id='my_string_id', auth_code='my_code', access_token_str='my_token',
      user_json=json.dumps({'id': '212038',
                            'name': 'Ryan Barrett',
                            'username': 'snarfed.org',
                            'bio': 'something about me',
                            'type': 'user',
                            }))
    self.auth_entity.put()

    self.post_activity = copy.deepcopy(as_facebook_test.ACTIVITY)
    self.post_activity['id'] = 'tag:facebook.com,2013:222' # this is fb_object_id

  def test_new(self):
    page = FacebookPage.new(self.handler, auth_entity=self.auth_entity)
    self.assertEqual(self.auth_entity, page.auth_entity.get())
    self.assertEqual('my_token', page.as_source.access_token)
    self.assertEqual('212038', page.key.id())
    self.assertEqual('http://graph.facebook.com/snarfed.org/picture?type=large',
                     page.picture)
    self.assertEqual('Ryan Barrett', page.name)
    self.assertEqual('snarfed.org', page.username)
    self.assertEqual('user', page.type)
    self.assertEqual('https://facebook.com/snarfed.org', page.silo_url())

  def test_get_activities(self):
    owned_event = copy.deepcopy(as_facebook_test.EVENT)
    owned_event['id'] = '888'
    owned_event['owner']['id'] = '212038'
    self.expect_urlopen(
      'https://graph.facebook.com/me/posts?offset=0&access_token=my_token',
      json.dumps({'data': [as_facebook_test.POST]}))
    self.expect_urlopen(
      'https://graph.facebook.com/me/photos/uploaded?access_token=my_token',
      json.dumps({'data': [as_facebook_test.POST]}))
    self.expect_urlopen(
      'https://graph.facebook.com/me/events?access_token=my_token',
      json.dumps({'data': [as_facebook_test.EVENT, owned_event]}))
    self.expect_urlopen(
      'https://graph.facebook.com/145304994?access_token=my_token',
      json.dumps(as_facebook_test.EVENT))
    self.expect_urlopen(
      'https://graph.facebook.com/888?access_token=my_token',
      json.dumps(owned_event))
    self.expect_urlopen(
      'https://graph.facebook.com/888/invited?access_token=my_token',
      json.dumps({'data': as_facebook_test.RSVPS}))
    self.mox.ReplayAll()

    page = FacebookPage.new(self.handler, auth_entity=self.auth_entity)
    event_activity = page.as_source.event_to_activity(owned_event)
    for k in 'attending', 'notAttending', 'maybeAttending', 'invited':
      event_activity['object'][k] = as_facebook_test.EVENT_OBJ_WITH_ATTENDEES[k]
    self.assert_equals([self.post_activity, as_facebook_test.ACTIVITY, event_activity],
                       page.get_activities())

  def test_get_activities_post_and_photo_duplicates(self):
    self.assertEqual(as_facebook_test.POST['object_id'],
                        as_facebook_test.PHOTO['id'])
    self.expect_urlopen(
      'https://graph.facebook.com/me/posts?offset=0&access_token=my_token',
      json.dumps({'data': [as_facebook_test.POST]}))
    self.expect_urlopen(
      'https://graph.facebook.com/me/photos/uploaded?access_token=my_token',
      json.dumps({'data': [as_facebook_test.PHOTO]}))
    self.expect_urlopen(
      'https://graph.facebook.com/me/events?access_token=my_token',
      json.dumps({}))
    self.mox.ReplayAll()

    page = FacebookPage.new(self.handler, auth_entity=self.auth_entity)
    self.assert_equals([self.post_activity], page.get_activities())

  def test_revoked(self):
    self.expect_urlopen(
      'https://graph.facebook.com/me/posts?offset=0&access_token=my_token',
      json.dumps({'error': {'code': 190, 'error_subcode': 458}}), status=400)
    self.mox.ReplayAll()

    page = FacebookPage.new(self.handler, auth_entity=self.auth_entity)
    self.assertRaises(models.DisableSource, page.get_activities)

  def test_expired_sends_notification(self):
    self.expect_urlopen(
      'https://graph.facebook.com/me/posts?offset=0&access_token=my_token',
      json.dumps({'error': {'code': 190, 'error_subcode': 463}}), status=400)

    params = {
      'template': "Brid.gy's access to your account has expired. Click here to renew it now!",
      'href': 'https://www.brid.gy/facebook/start',
      'access_token': 'my_app_id|my_app_secret',
      }
    self.expect_urlopen('https://graph.facebook.com/212038/notifications', '',
                        data=urllib.urlencode(params))
    self.mox.ReplayAll()

    page = FacebookPage.new(self.handler, auth_entity=self.auth_entity)
    self.assertRaises(models.DisableSource, page.get_activities)

  def test_other_error(self):
    self.expect_urlopen(
      'https://graph.facebook.com/me/posts?offset=0&access_token=my_token',
      json.dumps({'error': {'code': 190, 'error_subcode': 789}}), status=400)
    self.mox.ReplayAll()

    page = FacebookPage.new(self.handler, auth_entity=self.auth_entity)
    self.assertRaises(urllib2.HTTPError, page.get_activities)

  def test_other_error_not_json(self):
    """If an error body isn't JSON, we should raise the original exception."""
    self.expect_urlopen(
      'https://graph.facebook.com/me/posts?offset=0&access_token=my_token',
      'not json', status=400)
    self.mox.ReplayAll()

    page = FacebookPage.new(self.handler, auth_entity=self.auth_entity)
    self.assertRaises(urllib2.HTTPError, page.get_activities)

  def test_canonicalize_syndication_url(self):
    page = FacebookPage.new(self.handler, auth_entity=self.auth_entity)

    for expected, input in (
      ('https://facebook.com/212038/posts/314159',
       'http://facebook.com/snarfed.org/posts/314159'),
      ('https://facebook.com/212038/photos.php?fbid=314159',
       'https://www.facebook.com/snarfed.org/photos.php?fbid=314159'),
      ('https://facebook.com/212038/posts/314159',
       'https://facebook.com/permalink.php?story_fbid=314159&id=212038'),
      ('https://facebook.com/212038/posts/314159',
       'https://facebook.com/permalink.php?story_fbid=314159&amp;id=212038'),
      # make sure we don't touch user.name when it appears elsewhere in the url
      ('https://facebook.com/25624/posts/snarfed.org',
       'http://www.facebook.com/25624/posts/snarfed.org')):
      self.assertEqual(expected, page.canonicalize_syndication_url(input))

  def test_registration_callback(self):
    """Run through an authorization back and forth and make sure that
    the callback makes it all the way through.
    """
    encoded_state = urllib.quote_plus(
      '{"callback":"http://withknown.com/bridgy_callback",'
      '"feature":"publish","operation":"add"}')

    self.expect_urlopen(oauth_facebook.GET_ACCESS_TOKEN_URL % {
      'auth_code': 'fake-code',
      'client_id': appengine_config.FACEBOOK_APP_ID,
      'client_secret': appengine_config.FACEBOOK_APP_SECRET,
      'redirect_uri': urllib.quote_plus(
        'http://localhost/facebook/add?state=' + encoded_state)
    }, response='access_token=fake-access-token')

    self.expect_urlopen(
      oauth_facebook.API_USER_URL + '?access_token=fake-access-token',
      response=json.dumps(as_facebook_test.USER))

    self.mox.ReplayAll()

    resp = facebook.application.get_response(
      '/facebook/start', method='POST', body=urllib.urlencode({
        'feature': 'publish',
        'callback': 'http://withknown.com/bridgy_callback',
      }))

    self.assert_equals(302, resp.status_code)
    self.assert_equals(oauth_facebook.GET_AUTH_CODE_URL % {
      'scope': '',
      'client_id': appengine_config.FACEBOOK_APP_ID,
      'redirect_uri': urllib.quote_plus(
        'http://localhost/facebook/add?state=' + encoded_state),
    }, resp.headers['location'])

    resp = facebook.application.get_response(
      '/facebook/add?state=' + encoded_state +
      '&code=fake-code')

    self.assert_equals(302, resp.status_code)
    self.assert_equals('http://withknown.com/bridgy_callback',
                       resp.headers['location'])

    fb = FacebookPage.query().get()
    self.assert_(fb)
    self.assert_equals(as_facebook_test.USER['name'], fb.name)
    self.assert_equals([u'publish'], fb.features)
