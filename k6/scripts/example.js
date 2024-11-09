import http from 'k6/http';

export const options = {
  iterations: 10,
};

export default function () {
  http.get('https://test-api.k6.io/public/crocodiles/');
}