"""Placement diagnostic for the Intermediate level.

30 questions in a bank (5 per topic). A run picks 20-30 (default 25), balanced
across the six topics, in random order with shuffled answer options.
Kinds: predict output, fix a bug, explain a snippet, choose an approach.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

import config
from learner import TOPICS


@dataclass(frozen=True)
class Question:
    topic: str
    kind: str                # predict | fix | explain | approach
    prompt: str
    options: tuple[str, ...]
    answer: int              # index into options
    explain: str
    code: str = ""


def Q(topic, kind, prompt, options, answer, explain, code=""):
    return Question(topic, kind, prompt, tuple(options), answer, explain, code)


BANK: list[Question] = [
    # ---- syntax and types ----
    Q("syntax_types", "predict", "What does this print?",
      ["8", "53", "5 3", "An error"], 1,
      "Both values are strings, so + joins them: '5' + '3' is '53'.",
      'x = "5" + "3"\nprint(x)'),
    Q("syntax_types", "predict", "What does this print?",
      ["3.5 1", "3 1", "4 1", "3 0"], 1,
      "// is whole-number division (7 // 2 = 3) and % is the remainder (7 % 2 = 1).",
      "print(7 // 2, 7 % 2)"),
    Q("syntax_types", "fix", "This program should check whether the user is 18 or older, but it crashes. Which change fixes it?",
      ['Change line 1 to age = int(input("Age: "))', "Change line 2 to if age => 18:",
       'Change line 2 to if age >= "18":', "Change line 3 to print(age)"], 0,
      "input() always returns text (a str). int() turns it into a number you can compare with 18.",
      'age = input("Age: ")\nif age >= 18:\n    print("adult")'),
    Q("syntax_types", "predict", "What does this print?",
      ["True True", "True False", "False False", "False True"], 1,
      "5 == 5.0 is True (same value), but one is an int and the other a float, so the types differ.",
      "x = 5\ny = 5.0\nprint(x == y, type(x) == type(y))"),
    Q("syntax_types", "explain", "This code raises an error. Why?",
      ["Strings cannot be changed in place (they are immutable)", "name is a constant",
       "Index 0 does not exist", '"E" needs single quotes'], 0,
      "You cannot assign to part of a string. Build a new string instead, e.g. 'E' + name[1:].",
      'name = "Ada"\nname[0] = "E"'),

    # ---- control flow ----
    Q("control_flow", "predict", "What does this print?",
      ["1 2 3", "0 1 2", "0 1 2 3", "1 2"], 1,
      "range(3) produces 0, 1, 2. It starts at 0 and stops before 3.",
      'for i in range(3):\n    print(i, end=" ")'),
    Q("control_flow", "predict", "What does this print?",
      ["0", "2", "-2", "-4"], 2,
      "n goes 10, 6, 2, then -2. The loop stops once n > 0 is False, and -2 is printed.",
      "n = 10\nwhile n > 0:\n    n -= 4\nprint(n)"),
    Q("control_flow", "fix", "This should print the numbers 1 to 5 but stops at 4. What fixes it?",
      ["range(1, 6)", "range(0, 5)", "range(5)", "range(1, 4)"], 0,
      "range(start, stop) stops BEFORE stop, so use 6 to include 5.",
      "for i in range(1, 5):\n    print(i)"),
    Q("control_flow", "predict", "What does this print?",
      ["A", "B", "A then B", "C"], 0,
      "Python runs only the first branch whose condition is True. 7 > 5 is True, so it prints A and skips the rest.",
      'x = 7\nif x > 5:\n    print("A")\nelif x > 3:\n    print("B")\nelse:\n    print("C")'),
    Q("control_flow", "predict", "What does this print?",
      ["0 1 2 3", "0 1 2", "0 1 2 4", "0 1 2 3 4"], 1,
      "continue skips 3 (nothing is printed), and break stops the loop at 4 before printing it.",
      'for i in range(5):\n    if i == 3:\n        continue\n    if i == 4:\n        break\n    print(i, end=" ")'),

    # ---- functions and scope ----
    Q("functions_scope", "predict", "What does this print?",
      ["5", "None", "An error", "23"], 1,
      "The function computes a + b but never returns it, so it returns None.",
      "def add(a, b):\n    a + b\nprint(add(2, 3))"),
    Q("functions_scope", "predict", "What does this print?",
      ["5", "10", "An error", "None"], 1,
      "The x inside f is a separate local variable. The outer x is still 10.",
      "x = 10\ndef f():\n    x = 5\n    return x\nf()\nprint(x)"),
    Q("functions_scope", "explain", "This crashes with AttributeError: 'NoneType' object has no attribute 'upper'. Why?",
      ["greet prints but returns nothing, so msg is None", "name must be written in uppercase",
       "print cannot be used inside a function", "upper() needs an argument"], 0,
      "A function without a return statement gives back None. Return the text instead of printing it.",
      'def greet(name):\n    print("Hi", name)\nmsg = greet("Sam")\nprint(msg.upper())'),
    Q("functions_scope", "predict", "What does this print?",
      ["6 12", "2 4", "6 4", "12 12"], 0,
      "With no argument n defaults to 2, so f() is 6. f(4) is 12.",
      "def f(n=2):\n    return n * 3\nprint(f(), f(4))"),
    Q("functions_scope", "approach", "You write a function average(nums). What should it do with the answer so other code can use it?",
      ["Print it and return nothing", "Return it", "Store it in a global variable named result",
       "Ask the user to type it in"], 1,
      "Returning a value lets the caller print it, store it or use it in more calculations.",
      ""),

    # ---- data structures ----
    Q("data_structures", "predict", "What does this print?",
      ["4 4", "3 4", "4 3", "2 4"], 0,
      "append adds 4 at the end, so nums[-1] is 4 and the length is 4.",
      "nums = [3, 1, 2]\nnums.append(4)\nprint(nums[-1], len(nums))"),
    Q("data_structures", "predict", "What does this print?",
      ["['a', 'b']", "[1, 2]", "{'a': 1, 'b': 2}", "['b', 'a']"], 0,
      "sorted() on a dictionary sorts its keys and returns a list.",
      'd = {"a": 1}\nd["b"] = 2\nprint(sorted(d))'),
    Q("data_structures", "predict", "What does this print?",
      ["(1, 2)", "(2, 3)", "[2, 3]", "2"], 1,
      "t[1:] means 'from index 1 to the end', and slicing a tuple gives a tuple.",
      "t = (1, 2, 3)\nprint(t[1:])"),
    Q("data_structures", "approach", "You need to count how many times each word appears in a text. Which structure fits best?",
      ["A set of words", "A dictionary from word to count", "A tuple of words", "One long string"], 1,
      "A dictionary maps each word (key) to its count (value).",
      ""),
    Q("data_structures", "predict", "What does this print?",
      ["[1, 2]", "[1, 2, 3]", "[3]", "An error"], 1,
      "b = a does not copy the list. Both names point at the same list, so appending through b changes a.",
      "a = [1, 2]\nb = a\nb.append(3)\nprint(a)"),

    # ---- debugging ----
    Q("debugging", "explain", "You see IndexError: list index out of range on print(items[3]). What should you check first?",
      ["How many items the list holds and which index positions exist", "Whether Python is installed",
       "Whether the variable name is lowercase", "Whether the line ends with a colon"], 0,
      "A list with 3 items has indexes 0, 1 and 2. Check len(items) and the index you used.",
      ""),
    Q("debugging", "explain", "NameError: name 'totl' is not defined. The most likely cause is:",
      ["A misspelled variable name", "A missing colon", "An empty list", "Wrong indentation"], 0,
      "NameError means Python has never seen that name. Look for a typo (total vs totl).",
      ""),
    Q("debugging", "fix", "This gives a SyntaxError. What is the fix?",
      ["if x == 5:", "if x === 5:", "if x =! 5:", "if x is = 5:"], 0,
      "A single = stores a value; == compares two values.",
      'x = 5\nif x = 5:\n    print("five")'),
    Q("debugging", "approach", "Your program runs without errors but prints the wrong total. What is the best first debugging step?",
      ["Print the running total inside the loop to see where it goes wrong", "Delete the program and start again",
       "Wrap everything in try/except and ignore errors", "Run it again and hope"], 0,
      "Printing intermediate values shows exactly where reality and your expectation diverge.",
      ""),
    Q("debugging", "fix", "'Age: ' + 5 raises TypeError: can only concatenate str (not 'int') to str. Which fix works?",
      ["'Age: ' + str(5)", "'Age: ' - 5", "'Age: ' + [5]", "int('Age: ') + 5"], 0,
      "Join text with text: convert the number with str() first.",
      ""),

    # ---- problem solving ----
    Q("problem_solving", "approach", "To find the largest number in a list without using max(), a good plan is:",
      ["Keep a variable for the biggest value seen so far and update it while looping", "Add all the numbers together",
       "Count how many numbers there are", "Reverse the list and take the last item"], 0,
      "Compare each item with the best so far and keep the larger one.",
      ""),
    Q("problem_solving", "predict", "What does this print?",
      ["10", "24", "120", "4"], 1,
      "It multiplies 1 x 1 x 2 x 3 x 4 = 24 (that is 4 factorial).",
      "result = 1\nfor n in range(1, 5):\n    result *= n\nprint(result)"),
    Q("problem_solving", "approach", "sum(nums) / len(nums) computes an average. Which input would crash it?",
      ["An empty list", "A list with negative numbers", "A list with one item", "A list of floats"], 0,
      "len([]) is 0, and dividing by zero raises ZeroDivisionError. Always think about the empty case.",
      ""),
    Q("problem_solving", "approach", "Which expression reverses the string s?",
      ["s.reverse()", "s[::-1]", "reversed(s)", "s[-1]"], 1,
      "Slicing with a step of -1 returns the reversed string. Strings have no reverse() method, "
      "and reversed(s) returns an iterator, not a string.",
      ""),
    Q("problem_solving", "approach", "To test whether n > 1 is prime, which plan is correct?",
      ["Check that n is odd", "Check that n is not divisible by 10",
       "Try dividing by every number from 2 up to the square root of n; if none divides evenly, it is prime",
       "Check that n has two digits"], 2,
      "A prime has no divisor between 2 and its square root. The other checks give wrong answers (9 is odd but not prime).",
      ""),
]


def select_questions(n: int = config.DIAGNOSTIC_DEFAULT, seed: int | None = None) -> list[Question]:
    n = max(config.DIAGNOSTIC_MIN, min(config.DIAGNOSTIC_MAX, int(n)))
    rng = random.Random(seed)
    by_topic = {t: [q for q in BANK if q.topic == t] for t in TOPICS}
    base, extra = divmod(n, len(TOPICS))
    extra_topics = set(rng.sample(list(TOPICS), extra))
    chosen: list[Question] = []
    for t in TOPICS:
        k = base + (1 if t in extra_topics else 0)
        chosen += rng.sample(by_topic[t], min(k, len(by_topic[t])))
    rng.shuffle(chosen)
    return chosen


@dataclass
class Presented:
    question: Question
    options: list[str]
    answer: int


class DiagnosticRun:
    def __init__(self, n: int = config.DIAGNOSTIC_DEFAULT, seed: int | None = None):
        rng = random.Random(seed)
        self.items: list[Presented] = []
        for q in select_questions(n, seed):
            order = list(range(len(q.options)))
            rng.shuffle(order)
            self.items.append(Presented(q, [q.options[i] for i in order], order.index(q.answer)))
        self.index = 0
        self.results: list[tuple[str, bool]] = []

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def done(self) -> bool:
        return self.index >= self.total

    @property
    def current(self) -> Presented:
        return self.items[self.index]

    def answer(self, choice: int) -> bool:
        item = self.current
        correct = choice == item.answer
        self.results.append((item.question.topic, correct))
        self.index += 1
        return correct

    def summary(self) -> dict[str, tuple[int, int]]:
        out = {t: [0, 0] for t in TOPICS}
        for topic, ok in self.results:
            out[topic][1] += 1
            out[topic][0] += int(ok)
        return {t: (c, n) for t, (c, n) in out.items() if n}
