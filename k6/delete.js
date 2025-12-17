import http from "k6/http";
import { check, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://books-api.books-ai.svc.cluster.local";

const baseTitles = JSON.parse(open("./titles.json"));
const titles = [];
while (titles.length < 200) {
  titles.push(baseTitles[titles.length % baseTitles.length]);
}

export const options = {
  vus: 10,
  iterations: 60, // between 50 and 100 deletes per run
};

function randomItem() {
  return titles[Math.floor(Math.random() * titles.length)];
}

export default function () {
  const item = randomItem();
  // Try lookup to get an ISBN if present
  const lookup = http.get(`${BASE_URL}/books/title?title=${encodeURIComponent(item.title)}`);
  if (lookup.status === 200) {
    const body = lookup.json();
    const isbn = body?.isbn;
    if (isbn) {
      const res = http.del(`${BASE_URL}/books/${isbn}`);
      check(res, { "delete attempted": (r) => [200, 404].includes(r.status) });
    }
  }
  sleep(0.5);
}



