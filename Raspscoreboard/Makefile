# -----------------------------------------------------------------------
# Raspscoreboard — HUB75 LED scoreboard using hzeller/rpi-rgb-led-matrix
# -----------------------------------------------------------------------

RGB_LIB_DIR := lib/rpi-rgb-led-matrix

# Build the hzeller static library first, then link against it.
RGB_INCDIR  := $(RGB_LIB_DIR)/include
RGB_LIBDIR  := $(RGB_LIB_DIR)/lib
RGB_LIBRARY := $(RGB_LIBDIR)/librgbmatrix.a

TARGET  := scoreboard
SRCDIR  := src
SRCS    := $(wildcard $(SRCDIR)/*.cpp)
OBJS    := $(SRCS:.cpp=.o)

CXX     := g++
CXXFLAGS := -std=c++17 -O2 -Wall -Wextra -I$(RGB_INCDIR)
LDFLAGS  := -L$(RGB_LIBDIR) -lrgbmatrix -lrt -lm -lpthread

.PHONY: all clean lib

all: lib $(TARGET)

# Build the hzeller library
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
