"""Company FAQ knowledge base with a small pure-Python BM25 retriever.

Draft replies are grounded in these entries: the best matches are passed to the
LLM (AI mode) or used to fill the template (offline), and their ids are shown
to the reviewer as citations.
"""

import json
import math
import re
from collections import Counter
from dataclasses import dataclass

STOPWORDS = set("""
a an and are as at be by can could do does for from have hi hello how i if in is it me my of on or our
please so that the this to us we what when where which who why will with you your would like thanks thank
there any just get know let am was been has had they their them its
""".split())

# Words customers use -> words the FAQ uses.
SYNONYMS = {
    "money": "refund", "reimburse": "refund", "reimbursed": "refund", "refunded": "refund",
    "broken": "damaged", "smashed": "damaged", "cracked": "damaged", "chipped": "damaged", "faulty": "damaged",
    "bulk": "wholesale", "trade": "wholesale", "units": "wholesale",
    "ship": "dispatched", "shipping": "dispatched", "tracking": "dispatched", "processing": "dispatched",
    "book": "booking", "places": "booking", "class": "workshop",
    "pay": "payment", "card": "payment", "paypal": "payment",
    "abroad": "outside", "international": "outside",
}
TOKEN_RE = re.compile(r"[a-z0-9]+")
MIN_SCORE = 1.5  # weaker matches are not used as grounding


def _stem(word):
    for suffix in ("ings", "ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def tokenize(text, expand=False):
    tokens = []
    for word in TOKEN_RE.findall(text.lower()):
        if expand and word in SYNONYMS:
            tokens.append(_stem(SYNONYMS[word]))
        if word not in STOPWORDS:
            tokens.append(_stem(word))
    return tokens


@dataclass
class Entry:
    id: str
    question: str
    answer: str

    def as_dict(self, score=None):
        data = {"id": self.id, "question": self.question, "answer": self.answer}
        if score is not None:
            data["score"] = round(score, 2)
        return data


class KnowledgeBase:
    def __init__(self, entries, k1=1.5, b=0.75):
        self.entries = entries
        self.k1, self.b = k1, b
        # The question is repeated so a matching question weighs more than a passing word in an answer.
        self.docs = [Counter(tokenize(f"{e.question} {e.question} {e.answer}")) for e in entries]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg_len = sum(self.lengths) / max(len(entries), 1)
        df = Counter(term for doc in self.docs for term in doc)
        n = len(entries)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    @classmethod
    def load(cls, path):
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls([Entry(e["id"], e["question"], e["answer"]) for e in data["entries"]])

    def _score(self, query, idx):
        doc, length, total = self.docs[idx], self.lengths[idx], 0.0
        for term in query:
            tf = doc.get(term, 0)
            if tf:
                total += self.idf[term] * tf * (self.k1 + 1) / (
                    tf + self.k1 * (1 - self.b + self.b * length / self.avg_len))
        return total

    def search(self, text, top_k=2, min_score=MIN_SCORE):
        """Return [(score, Entry)] best first, only matches above min_score."""
        query = tokenize(text, expand=True)
        scored = [(self._score(query, i), e) for i, e in enumerate(self.entries)]
        scored = [pair for pair in scored if pair[0] >= min_score]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[:top_k]
