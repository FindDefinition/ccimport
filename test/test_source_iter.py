from ccimport.source_iter import CppSourceIterator


def test_source_iter():
    source = (
        "std::cout << L\"hello\" << \" world\";\n"
        "std::cout << \"He said: \\\"bananas\\\"\" << \"...\";\n"
        "std::cout << \"\";\n"
        "std::cout << \"\\x12\\23\\x34\";\n"
        "std::cout << u8R\"hello(this\"is\\a\\\"\"\"\"single\\\\(valid)\"\n"
        "raw string literal)hello\";\n\n"
        "_ci_test_asd( int a, std::string b = \"asd\"  ) { }\n"
        "_ci_test_asdex(){ }\n"
        "\"\" // empty string\n"
        "'\"' // character literal\n\n"
        "// this is \"a string literal\" in a comment\n"
        "/* this is\n"
        "   \"also inside\"\n"
        "   //a comment */\n\n"
        "// and this /*\n"
        "\"is not in a comment\"\n"
        "// */\n\n"
        "\"this is a /* string */ with nested // comments\"\n\n")
    siter = CppSourceIterator(source)
    for meta in siter.find_identifier_prefix("_ci_test_"):
        siter.reset_bracket_count().move(meta.end)
        pair = siter.next_round()
        assert pair is not None
        pair = siter.next_curly()
        assert pair is not None

    return siter.identifiers


def test_source_iter2():
    source = """
int pytime_fromtimespec(_PyTime_t &tp, const timespec &ts) {
  int res = 0;
  _PyTime_t t = ts.tv_sec;
  _PyTime_t nsec;
  if (_PyTime_check_mul_overflow(t, SEC_TO_NS)) {
    res = -1;
    t = (t > 0) ? _PyTime_MAX : _PyTime_MIN;
  } else {
    t = t * SEC_TO_NS;
  }

  nsec = ts.tv_nsec;
  /* The following test is written for positive only nsec */
  assert(nsec >= 0);
  if (t > _PyTime_MAX - nsec) {
    res = -1;
    t = _PyTime_MAX;
  } else {
    t += nsec;
  }
  tp = t;
  return res;
}
class A {

};
int CODEAI_EXPORT pygettimeofday(_PyTime_t &tp) {
  // adapted from cpython pytime.c
  struct timespec ts;
  auto err = clock_gettime(CLOCK_REALTIME, &ts);
  if (err) {
    return -1;
  }
  return pytime_fromtimespec(tp, ts);
}

int  _PyTime_GetThreadTime(_PyTime_t &tp) {
  // adapted from cpython pytime.c
  struct timespec ts;
  const clockid_t clk_id = CLOCK_THREAD_CPUTIME_ID;

  auto err = clock_gettime(clk_id, &ts);
  if (err) {
    return -1;
  }
  return pytime_fromtimespec(tp, ts);
}
    """
    siter = CppSourceIterator(source)
    print(siter.find_function_prefix("pygettim"))
    print(list(siter.find_all_class_def()))
    print(siter.find_function_prefix("CODEAI_EXPORT", find_after=True))


if __name__ == "__main__":
    test_source_iter2()
