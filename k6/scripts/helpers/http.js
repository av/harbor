import { check } from "k6";
import { Trend } from "k6/metrics";
import http from "k6/http";
import { mergeDeep } from './utils.js';

const graphqlTrends = {
  entities: new Trend('graphql_entities'),
  errors: new Trend('graphql_errors'),
};

export function get(url, params) {
  const response = http.get(url, params);
  check(response, {
    "status is 200": (r) => r.status === 200,
  });

  if (__ENV.NETWORK_DEBUG === 'true') {
    console.log('===============');
    console.log('HTTP:', url, response.status, response.status_text);
    // console.log(JSON.stringify(response, null, 2));
    console.log('===============');
  }

  return response;
}

export function getRequest(url, params) {
  return {
    method: 'GET',
    url,
    params,
  };
}

export function post(url, body, params) {
  if (typeof body !== 'string') {
    body = JSON.stringify(body);
  }

  const response = http.post(url, body, params);
  check(response, {
    "status is 200": (r) => r.status === 200,
  });
  return response;
}


export function postRequest(url, body, params) {
  return {
    method: 'POST',
    url,
    body,
    params,
  };
}

export function graphql(url, query, variables = {}, params = {}) {
  const response = post(
    url,
    JSON.stringify({
      query,
      variables,
    }),
    mergeDeep(params, {
      headers: {
        "Content-Type": "application/json"
      }
    }),
  );

  if (__ENV.NETWORK_DEBUG === 'true') {
    console.log('===============');
    console.log('GRAPHQL:', url, response.status, response.status_text);
    console.log(JSON.stringify({
      query,
      variables,
      params,
      // response: getBody(response)
    }, null, 2));
    console.log('===============');
  }

  if (__ENV.GRAPHQL_TRENDS === 'true') {
    let body;

    body = getBody(response);

    if (body) {
      if (body.data) {
        const fields = Object.keys(body.data);

        for (const field of fields) {
          const value = body.data[field];

          graphqlTrends.entities.add(
            Array.isArray(value) ? value.length : 1,
            {
              field,
            }
          );
        }
      }

      if (body.errors) {
        graphqlTrends.errors.add(Array.isArray(body.errors) ? body.errors.length : 1);
      }
    }
  }

  return response;
}

export function graphqlRequest(url, query, variables = {}, params = {}) {
  return {
    method: 'POST',
    url,
    body: JSON.stringify({
      query,
      variables,
    }),
    params: mergeDeep(params, {
      headers: {
        'Content-Type': 'application/json',
      },
    }),
  };
}

/**
 * Tries to parse the body as JSON and logs an error if it fails to do so.
 * Useful when you may occasionally receive non-JSON responses (for example 502/3/4 from ALB).
 */
export function getBody(response) {
  try {
    return response.json();
  } catch(e) {
    const maybeBody = ((response && response.body) || '');
    const maybePreview = maybeBody.slice(0, 500);

    console.error(`Not a JSON:\n${maybePreview}\nStatus: ${response.status}\nHeaders: ${JSON.stringify(response.headers)}}`);
  }
}