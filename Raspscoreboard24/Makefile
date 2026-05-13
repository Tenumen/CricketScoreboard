# ---------------------------------------------------------------------------
# Raspscoreboard24 — 24-panel (6 wide x 4 deep) HUB75 scoreboard
# Fork of ../Raspscoreboard/. Shares the rpi-rgb-led-matrix submodule via
# lib/rpi-rgb-led-matrix which is a symlink to ../Raspscoreboard/lib/...
# ---------------------------------------------------------------------------

RGB_LIB_DIR := lib/rpi-rgb-led-matrix

RGB_INCDIR  := $(RGB_LIB_DIR)/include
RGB_LIBDIR  := $(RGB_LIB_DIR)/lib
RGB_LIBRARY := $(RGB_LIBDIR)/librgbmatrix.a

TARGET  := scoreboard24
SRCDIR  := src
SRCS    := $(wildcard $(SRCDIR)/*.cpp)
OBJS    := $(SRCS:.cpp=.o)

CXX      := g++
CXXFLAGS := -std=c++17 -O2 -Wall -Wextra -I$(RGB_INCDIR) -I$(SRCDIR)
LDFLAGS  := -L$(RGB_LIBDIR) -lrgbmatrix -lrt -lm -lpthread

.PHONY: all clean clean-all lib

all: lib $(TARGET)

lib:
	$(MAKE) -C $(RGB_LIB_DIR)/lib

$(TARGET): $(OBJS) $(RGB_LIBRARY)
	$(CXX) $(OBJS) -o $@ $(LDFLAGS)

$(SRCDIR)/%.o: $(SRCDIR)/%.cpp
	$(CXX) $(CXXFLAGS) -c $< -o $@

clean:
	rm -f $(TARGET) $(OBJS)

clean-all: clean
	$(MAKE) -C $(RGB_LIB_DIR)/lib clean
