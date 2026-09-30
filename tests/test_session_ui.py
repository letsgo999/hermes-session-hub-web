import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "src" / "session_hub" / "static" / "app.js"


class SessionUiTests(unittest.TestCase):
    def test_message_button_toggles_one_cached_pre_without_refetch(self):
        script = r"""
const assert = require("assert");
const { renderSessions } = require(process.argv[1]);

class FakeNode {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.listeners = {};
    this.parentNode = null;
    this.textContent = "";
  }
  append(...nodes) {
    for (const node of nodes) {
      if (node.parentNode) node.remove();
      node.parentNode = this;
      this.children.push(node);
    }
  }
  replaceChildren(...nodes) {
    for (const child of this.children) child.parentNode = null;
    this.children = [];
    this.append(...nodes);
  }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  remove() {
    if (!this.parentNode) return;
    this.parentNode.children = this.parentNode.children.filter((item) => item !== this);
    this.parentNode = null;
  }
  async click() { return this.listeners.click(); }
}

global.document = { createElement: (tag) => new FakeNode(tag) };
global.navigator = {};
global.location = { href: "" };
let fetchCount = 0;
global.fetch = async () => {
  fetchCount += 1;
  return {
    ok: true,
    headers: { get: () => "application/json" },
    json: async () => ({ messages: [{ role: "user", content: "hello" }] }),
  };
};

(async () => {
  const list = new FakeNode("section");
  renderSessions(list, [{ id: "sess_alpha", title: "A", profile_id: "default" }]);
  const card = list.children[0];
  const button = card.children.find((item) => item.tagName === "BUTTON");
  assert.equal(button.textContent, "메시지 보기");

  await button.click();
  assert.equal(button.textContent, "메시지 접기");
  assert.equal(card.children.filter((item) => item.tagName === "PRE").length, 1);
  assert.equal(fetchCount, 1);

  await button.click();
  assert.equal(button.textContent, "메시지 보기");
  assert.equal(card.children.filter((item) => item.tagName === "PRE").length, 0);
  assert.equal(fetchCount, 1);

  await button.click();
  assert.equal(button.textContent, "메시지 접기");
  assert.equal(card.children.filter((item) => item.tagName === "PRE").length, 1);
  assert.equal(fetchCount, 1);
})().catch((error) => { console.error(error); process.exit(1); });
"""
        completed = subprocess.run(
            ["node", "-e", script, str(APP_JS)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()