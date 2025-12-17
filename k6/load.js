import http from "k6/http";
import { check, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://books-api.books-ai.svc.cluster.local";

const baseTitles = JSON.parse(open("./titles.json"));
const titles = [];
while (titles.length < 200) {
  titles.push(baseTitles[titles.length % baseTitles.length]);
}

let pointer = 0;

export const options = {
  scenarios: {
    steady_load: {
      executor: "constant-arrival-rate",
      rate: 30, // requests per minute (between 10 and 60)
      timeUnit: "1m",
      duration: "15m",
      preAllocatedVUs: 20,
      maxVUs: 50,
    },
  },
};

function nextTitle() {
  const item = titles[pointer % titles.length];
  pointer += 1;
  return item;
}

export default function () {
  const item = nextTitle();
  const search = http.get(`${BASE_URL}/books/title?title=${encodeURIComponent(item.title)}`);

  if (search.status === 404) {
    const payload = JSON.stringify({
      title: item.title,
      author_first_name: item.author_first_name,
      author_last_name: item.author_last_name,
    });
    const createRes = http.post(`${BASE_URL}/books`, payload, {
      headers: { "Content-Type": "application/json" },
    });
    check(createRes, {
      "create status ok": (r) => [200, 201, 422].includes(r.status),
    });
  } else {
    check(search, { "lookup ok": (r) => r.status === 200 });
  }

  sleep(1);
}



