# ---------------------------------------------------------------------------
# Raspscoreboard24 — 24-panel (6 wide x 4 deep) HUB75 scoreboard
#
#   make                          # default: hub75 backend, real Pi binary
#   make RENDER_BACKEND=hub75     # same as default
#   make RENDER_BACKEND=headless  # x86/Ubuntu sim binary, no HUB75 hardware
#   make all-backends             # both at once (separate object dirs)
#
# Object files live under build/<backend>/ so the two backends don't collide.
# ---------------------------------------------------------------------------

RGB_LIB_DIR := lib/rpi-rgb-led-matrix
RGB_INCDIR  := $(RGB_LIB_DIR)/include
RGB_LIBDIR  := $(RGB_LIB_DIR)/lib
RGB_LIBRARY := $(RGB_LIBDIR)/librgbmatrix.a

SRCDIR    := src
THIRD_DIR := third_party
RGB_GFX_DIR := $(THIRD_DIR)/rgb_graphics

RENDER_BACKEND ?= hub75

CXX       := g++

# Short git hash baked into the binary as BUILD_GIT_HASH so the admin
# console can display the commit the running binary was built from.
# To force a fresh hash without touching source: `touch src/debug_server.cpp`.
BUILD_GIT_HASH := $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)

CXX_BASE  := -std=c++17 -O2 -Wall -Wextra -I$(SRCDIR) -I$(THIRD_DIR) \
             -DBUILD_GIT_HASH=\"$(BUILD_GIT_HASH)\"

# ---------- per-backend source/flag selection ----------
COMMON_SRCS := \
    $(SRCDIR)/main.cpp \
    $(SRCDIR)/grid_canvas.cpp \
    $(SRCDIR)/poll_loop.cpp \
    $(SRCDIR)/play_cricket_client.cpp \
    $(SRCDIR)/match_mapping.cpp \
    $(SRCDIR)/debug_server.cpp \
    $(SRCDIR)/calibration.cpp \
    $(SRCDIR)/effects/event_detect.cpp \
    $(SRCDIR)/effects/event_splash.cpp \
    $(SRCDIR)/effects/fireworks.cpp

ifeq ($(RENDER_BACKEND),hub75)
  TARGET   := scoreboard24
  BUILDDIR := build/hub75
  CXXFLAGS := $(CXX_BASE) -I$(RGB_INCDIR)
  LDFLAGS  := -L$(RGB_LIBDIR) -lrgbmatrix -lrt -lm -lpthread -lcurl
  BACKEND_SRCS := $(SRCDIR)/render_backend/hub75_backend.cpp
  # Optional frame emitter on the real Pi: `make EMIT_FRAMES=1` -- but the
  # current hub75 backend cannot read FrameCanvas bytes, so this is a no-op
  # placeholder until the library is patched.
  ifdef EMIT_FRAMES
    CXXFLAGS    += -DCRICKETBOARD_EMIT_FRAMES
    BACKEND_SRCS += $(SRCDIR)/render_backend/frame_emitter.cpp
  endif
  BACKEND_OBJS_EXTRA :=
  LIB_TARGET := $(RGB_LIBRARY)
  LIB_DEP    := lib
else ifeq ($(RENDER_BACKEND),headless)
  TARGET   := scoreboard24-sim
  BUILDDIR := build/headless
  # Headless build vendors graphics primitives so we don't link librgbmatrix
  CXXFLAGS := $(CXX_BASE) -I$(RGB_GFX_DIR) -DCRICKETBOARD_HEADLESS
  LDFLAGS  := -lpthread -lcurl
  BACKEND_SRCS := \
      $(SRCDIR)/render_backend/headless_backend.cpp \
      $(SRCDIR)/render_backend/frame_emitter.cpp
  # Vendored graphics primitives (BDF font + DrawText/DrawLine). These have
  # no hardware deps and compile into the headless binary directly.
  BACKEND_OBJS_EXTRA := $(BUILDDIR)/third_party/graphics.o $(BUILDDIR)/third_party/bdf-font.o
  LIB_TARGET :=
  LIB_DEP    :=
else
  $(error Unknown RENDER_BACKEND='$(RENDER_BACKEND)'. Use hub75 or headless.)
endif

ALL_SRCS := $(COMMON_SRCS) $(BACKEND_SRCS)
# Each source file becomes build/<backend>/path/to/file.o
ALL_OBJS := $(patsubst $(SRCDIR)/%.cpp,$(BUILDDIR)/%.o,$(ALL_SRCS)) $(BACKEND_OBJS_EXTRA)

.PHONY: all clean clean-all lib all-backends help

all: $(LIB_DEP) $(TARGET)

help:
	@echo "Targets:"
	@echo "  make                          - build hub75 binary"
	@echo "  make RENDER_BACKEND=headless  - build sim binary"
	@echo "  make all-backends             - build both"
	@echo "  make clean                    - remove this backend's build dir + binary"
	@echo "  make clean-all                - clean everything including librgbmatrix"

all-backends:
	$(MAKE) RENDER_BACKEND=hub75
	$(MAKE) RENDER_BACKEND=headless

lib:
	$(MAKE) -C $(RGB_LIB_DIR)/lib

$(TARGET): $(ALL_OBJS) $(LIB_TARGET)
	$(CXX) $(ALL_OBJS) -o $@ $(LDFLAGS)

# src/*.cpp under subdirs (render_backend/) too -- pattern keeps the subdir.
$(BUILDDIR)/%.o: $(SRCDIR)/%.cpp
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) -c $< -o $@

# Vendored graphics primitives only used by headless build.
$(BUILDDIR)/third_party/graphics.o: $(RGB_GFX_DIR)/graphics.cc
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) -c $< -o $@

$(BUILDDIR)/third_party/bdf-font.o: $(RGB_GFX_DIR)/bdf-font.cc
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) -c $< -o $@

clean:
	rm -f $(TARGET)
	rm -rf $(BUILDDIR)
	# Also clean stale .o files left next to sources by older Makefile
	find $(SRCDIR) -name '*.o' -delete 2>/dev/null || true

clean-all:
	rm -f scoreboard24 scoreboard24-sim
	rm -rf build
	find $(SRCDIR) -name '*.o' -delete 2>/dev/null || true
	-$(MAKE) -C $(RGB_LIB_DIR)/lib clean
