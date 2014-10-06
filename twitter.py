"""Twitter source code and datastore model classes.
"""

__author__ = ['Ryan Barrett <bridgy@ryanb.org>']

import datetime
import json
import logging

import webapp2

import appengine_config

from activitystreams import twitter as as_twitter
from activitystreams.oauth_dropins import twitter as oauth_twitter
import models
import util


class Twitter(models.Source):
  """A Twitter account.

  The key name is the username.
  """

  AS_CLASS = as_twitter.Twitter
  SHORT_NAME = 'twitter'
  TYPE_LABELS = {'post': 'tweet',
                 'comment': '@-reply',
                 'repost': 'retweet',
                 'like': 'favorite',
                 }

  # Twitter's rate limiting window is currently 15m. A normal poll with nothing
  # new hits /statuses/user_timeline and /search/tweets once each. Both
  # allow 180 calls per window before they're rate limited.
  # https://dev.twitter.com/docs/rate-limiting/1.1/limits
  FAST_POLL = datetime.timedelta(minutes=10)

  @staticmethod
  def new(handler, auth_entity=None, **kwargs):
    """Creates and returns a Twitter entity.

    Args:
      handler: the current RequestHandler
    """
    user = json.loads(auth_entity.user_json)
    as_source = as_twitter.Twitter(*auth_entity.access_token())
    actor = as_source.user_to_actor(user)
    return Twitter(id=user['screen_name'],
                   auth_entity=auth_entity.key,
                   url=actor.get('url'),
                   name=actor.get('displayName'),
                   picture=actor.get('image', {}).get('url'),
                   **kwargs)

  def silo_url(self):
    """Returns the Twitter account URL, e.g. https://twitter.com/foo."""
    return self.as_source.user_url(self.key.id())

  def get_like(self, activity_user_id, activity_id, like_user_id):
    """Returns an ActivityStreams 'like' activity object for a favorite.

    We get Twitter favorites by scraping HTML, and we only get the first page,
    which only has 25. So, use a Response in the datastore first, if we have
    one, and only re-scrape HTML as a fallback.

    Args:
      activity_user_id: string id of the user who posted the original activity
      activity_id: string activity id
      like_user_id: string id of the user who liked the activity
    """
    id = self.as_source.tag_uri('%s_favorited_by_%s' % (activity_id, like_user_id))
    resp = models.Response.get_by_id(id)
    if resp:
      return json.loads(resp.response_json)
    else:
      return super(Twitter, self).get_like(activity_user_id, activity_id,
                                           like_user_id)


class AddTwitter(oauth_twitter.CallbackHandler, util.Handler):
  def finish(self, auth_entity, state=None):
    source = self.maybe_add_or_delete_source(Twitter, auth_entity, state)
    feature = self.decode_state_parameter(state).get('feature')
    if source is not None and feature == 'listen' and 'publish' in source.features:
      # if we were already signed up for publish, we had a read/write token.
      # when we sign up for listen, we use x_auth_access_type=read to request
      # just read permissions, which *demotes* us to a read only token! ugh.
      source.features.remove('publish')
      source.put()


class StartHandler(util.Handler):
  """Custom OAuth start handler so we can use access_type=read for state=listen.

  Tweepy converts access_type to x_auth_access_type for Twitter's
  oauth/request_token endpoint. Details:
  https://dev.twitter.com/docs/api/1/post/oauth/request_token
  """
  def post(self):
    state = self.request.get('state')
    if not state:
      state = self.construct_state_param(state)
      self.request.GET['state'] = state
    feature = self.decode_state_parameter(state).get('feature')
    if not state:
      self.abort(400, 'Missing or malformed "state" parameter: %s' % state)
    # pass explicit 'write' instead of None for publish so that oauth-dropins
    # (and tweepy) don't use signin_with_twitter ie /authorize. this works
    # around a twitter API bug: https://dev.twitter.com/discussions/21281
    access_type = 'read' if feature == 'listen' else 'write'
    handler = oauth_twitter.StartHandler.to(
      '/twitter/add', access_type=access_type)(self.request, self.response)
    return handler.post()


application = webapp2.WSGIApplication([
    ('/twitter/start', StartHandler),
    ('/twitter/add', AddTwitter),
    ('/twitter/delete/finish', oauth_twitter.CallbackHandler.to('/delete/finish')),
    ], debug=appengine_config.DEBUG)
