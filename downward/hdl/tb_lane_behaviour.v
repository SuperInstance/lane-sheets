// tb_lane_behaviour.v -- FABRIC BEHAVIOUR SPIKE (lane-sheets line).
//
// Question: the QUF image triage-clean-nocrc.quf BOOTS the quilt-verilog
// fabric (falsifier lane, LANE_BOOT PASS) but no workflow has ever RUN on
// the booted fabric. This TB drives the op sequence DOWNWARD.md predicts
// for triage-clean's clean workflow (3 value cells + 2 edges, one inject
// step, tick_tpw 6) through the fabric's own serialized front end
// (q_serfabric_top, SER_BOOT_QUF=1, NCELL=3), in the harness style of
// tb/tb_serfabric.v (sendbyte / packflit / serialized egress capture /
// waitrun copied in shape), and reads the resulting state back two ways:
// the fabric-native VIEW op (act / wsum / dial rows) and hierarchical
// probes of the ladder engines (house style, cf. tb_serfabric A1).
//
// Phases:
//   P0 boot the nocrc image (broadcast), expect RUN + epoch.
//   P1 BIND cells 0,1,2 (workflow ids 1,2,3 at fabric addresses 0,1,2 --
//      QUF-NOTES D1 rank order). ACK per bind.
//   P2 dial readback, all 3 cells x 16 dials, vs the image rows.
//   P3 LINK the two workflow edges. The live core matches an incoming
//      EFFECT against ITS OWN edge table (q_cell_core ST_EFFT), so a
//      directed edge needs a pairing at BOTH endpoints (the idiom
//      tb_fabric_smoke.v step 5 proves); the QUF image stores each edge
//      once, at its source. wsum readbacks verify the links.
//      Plus a negative probe: an EFFECT with an unmatched src is
//      silently dropped (no egress, no act change).
//   P4 16-tick dynamics window, no inject: steady-state probes.
//   P5 the sheet's inject as the naive mapping writes it (EFFECT src =
//      the external port id, no port pairing installed): observe.
//   P6 install the port pairing (LINK dst 0 src EXTID slot 1, base
//      0x8000 = identity scaling), re-inject dat 42: observe act, the
//      first tick boundary, and whether anything propagates.
//   P7 per-tick decay series on the once-trained port edge.
//   P8 final dial readback (hash-level comparison input).
//   P9 compensation run, fresh boot: pin KA=15, HL=0xFFFF on all cells
//      and THRESH=0x7FFF on the sink cell via BIND dial writes, then
//      re-run the window + inject and measure what the pins change.
//
// Checks assert the FABRIC-side predictions (RTL semantics, read from
// rtl/q_cell_core.v, rtl/q_hebb_edge.v, rtl/q_dialfile.v). OBSERVE lines
// print the measured values BEHAVIOUR.md reports; a sheet-vs-fabric
// divergence is an OBSERVE result, not a check failure.
//
// Run (from the quilt-verilog clone root):
//   iverilog -g2005 -s tb_lane_behaviour -o tb/run/tb_lane_behaviour.vvp \
//     <suite RTL> <serfabric RTL> tb_lane_behaviour.v
//   vvp tb/run/tb_lane_behaviour.vvp
// Image hex: tb/run/triage-nocrc.hex (count-first %h, tb_lane_boot style).
`timescale 1ns/1ps
module tb_lane_behaviour;
    reg clk = 0, por = 0;
    always #5 clk = ~clk;

    integer errors = 0;
    integer cyc = 0;
    always @(posedge clk) cyc <= cyc + 1;

    // ---------------- DUT: serialized QUF-booted fabric, 3 cells ------
    reg         s_sval = 0, s_eod = 0;
    reg  [7:0]  s_sbyte = 0;
    wire        s_srdy, s_stx_val, s_boot_ok, s_epoch, s_ovf;
    wire [7:0]  s_stx;
    wire [2:0]  s_state;
    wire [7:0]  s_err;

    q_serfabric_top #(.NCELL(3), .SER_BOOT_QUF(1)) dut (
        .clk(clk), .rst_n(por),
        .i_sval(s_sval), .o_srdy(s_srdy), .i_sbyte(s_sbyte), .i_eod(s_eod),
        .o_stx_val(s_stx_val), .i_strdy(1'b1), .o_stx(s_stx),
        .o_boot_ok(s_boot_ok), .o_epoch(s_epoch),
        .o_state(s_state), .o_err(s_err), .o_ovf(s_ovf)
    );

    reg saw_boot = 0, saw_epoch = 0;
    always @(s_boot_ok) if (s_boot_ok === 1'b1) saw_boot  = 1;
    always @(s_epoch)   if (s_epoch   === 1'b1) saw_epoch = 1;

    // tick counter: one broadcast tick pulse per 2^6 = 64 cycles
    integer tickcount = 0;
    always @(posedge clk) if (dut.tick === 1'b1) tickcount = tickcount + 1;

    // ---------------- serialized egress capture (tb_serfabric shape) --
    integer sc = 0, sbytes = 0;
    reg [79:0] sacc;
    reg [2:0]  sc_op   [0:1023];
    reg [3:0]  sc_src  [0:1023], sc_dst [0:1023];
    reg [15:0] sc_a0   [0:1023], sc_a1 [0:1023];
    reg [15:0] sc_a2   [0:1023], sc_dat [0:1023];
    integer    sc_cyc  [0:1023];
    always @(posedge clk) if (s_stx_val && 1'b1) begin
        sacc = {sacc[71:0], s_stx};
        if (sbytes == 0 && sc < 1023) sc_cyc[sc] = cyc;
        sbytes = sbytes + 1;
        if (sbytes == 10) begin
            sbytes = 0;
            if (sacc[4:0] !== 5'd0) begin
                errors = errors + 1;
                $display("FAIL egress pad bits nonzero (%h)", sacc[4:0]);
            end
            if (sc < 1023) begin
                sc_op[sc] = sacc[79:77]; sc_src[sc] = sacc[76:73];
                sc_dst[sc] = sacc[72:69];
                sc_a0[sc] = sacc[68:53]; sc_a1[sc] = sacc[52:37];
                sc_a2[sc] = sacc[36:21]; sc_dat[sc] = sacc[20:5];
                sc = sc + 1;
            end
        end
    end
    integer consumed = 0;   // egress flits popped by recv tasks

    // ---------------- helpers (harness tasks, tb_serfabric shape) -----
    task check(input cond, input [511:0] name);
        begin
            if (cond !== 1'b1) begin
                errors = errors + 1;
                $display("FAIL %0s (t=%0t state=%0d err=%0d)",
                         name, $time, s_state, s_err);
            end
        end
    endtask

    task sendbyte(input [7:0] b);
        begin
            @(negedge clk);
            s_sval = 1; s_sbyte = b;
            while (s_srdy !== 1'b1) @(negedge clk);
            @(negedge clk);
            s_sval = 0;
        end
    endtask

    function [79:0] packflit(input [2:0] op, input [3:0] src,
                             input [3:0] dst, input [15:0] a0,
                             input [15:0] a1, input [15:0] a2,
                             input [15:0] dat);
        begin
            packflit = {op, src, dst, a0, a1, a2, dat, 5'd0};
        end
    endfunction

    // serialized flit, 10 bytes MSB-first (tb_serfabric serflit_solo)
    task serflit(input [2:0] op, input [3:0] src, input [3:0] dst,
                 input [15:0] a0, input [15:0] a1, input [15:0] a2,
                 input [15:0] dat);
        integer k;
        reg [79:0] sh;
        begin
            sh = packflit(op, src, dst, a0, a1, a2, dat);
            for (k = 0; k < 10; k = k + 1)
                sendbyte(sh[79 - 8*k -: 8]);
        end
    endtask

    task waitrun;
        integer n;
        begin
            n = 0;
            while (s_state !== 3'd5 && n < 100000) begin
                @(negedge clk); n = n + 1;
            end
            repeat (4) @(negedge clk);
        end
    endtask

    // pop the next egress flit (ACK/NAK responses addressed to EXTID)
    task recv_flit;
        output [2:0]  op;
        output [3:0]  src;
        output [15:0] dat;
        input  [511:0] name;
        integer n;
        begin
            n = 0;
            while (consumed >= sc && n < 20000) begin
                @(negedge clk); n = n + 1;
            end
            check(consumed < sc, name);
            if (consumed < sc) begin
                op  = sc_op[consumed];
                src = sc_src[consumed];
                dat = sc_dat[consumed];
                consumed = consumed + 1;
            end else begin
                op = 3'd7; src = 4'd0; dat = 16'hXXXX;
            end
            repeat (30) @(negedge clk);   // ring settle margin
        end
    endtask

    // VIEW one quantity from one cell; returns the ACK dat payload.
    // mode 0 = act, 1 = wsum, 2 = dial[a1]
    task view;
        input  [3:0]  cid;
        input  [15:0] mode;
        input  [15:0] idx;
        output [15:0] val;
        reg [2:0] rop;
        reg [3:0] rsrc;
        reg [15:0] rdat;
        begin
            serflit(3'd3, 4'hF, cid, mode, idx, 16'd0, 16'd0);
            recv_flit(rop, rsrc, rdat, "view response arrives");
            check(rop === 3'd5, "view answered with ACK (OP_ACK = 5)");
            check(rsrc === cid, "view response src is the viewed cell");
            val = rdat;
        end
    endtask

    // wait until tickcount reaches base+n (sampled at negedge)
    task wait_ticks(input [31:0] base, input [31:0] n);
        integer guard;
        begin
            guard = 0;
            while (tickcount < base + n && guard < 200000) begin
                @(negedge clk); guard = guard + 1;
            end
            repeat (50) @(negedge clk);   // let the tick's services land
        end
    endtask

    // ---------------- image -------------------------------------------
    integer fd, r, nbytes, tmpi, i;
    reg [7:0] imem [0:65535];
    initial begin
        $timeformat(-9, 0, " ns", 10);
        fd = $fopen("tb/run/triage-nocrc.hex", "r");
        if (fd == 0) begin
            $display("FAIL: cannot open tb/run/triage-nocrc.hex");
            $finish;
        end
        r = $fscanf(fd, "%h", nbytes);
        if (r != 1 || nbytes <= 0 || nbytes > 65536) begin
            $display("FAIL: bad hex header");
            $finish;
        end
        for (i = 0; i < nbytes; i = i + 1) begin
            r = $fscanf(fd, "%h", tmpi);
            if (r != 1) begin
                $display("FAIL: hex truncated at %0d", i);
                $finish;
            end
            imem[i] = tmpi[7:0];
        end
        $fclose(fd);
        $display("BEHAVIOUR: %0d-byte triage-clean-nocrc image", nbytes);
    end

    // expected dial rows from the image (triage-clean.json dial arrays)
    // cell 0 (id 1): all zero except dial5 = 12000
    // cell 1 (id 2): all zero except dial5 = 8000
    // cell 2 (id 3): all zero
    function [15:0] img_dial;
        input [31:0] cid;
        input [31:0] idx;
        begin
            if (idx == 5 && cid == 0)      img_dial = 16'd12000;
            else if (idx == 5 && cid == 1) img_dial = 16'd8000;
            else                           img_dial = 16'd0;
        end
    endfunction

    reg [2:0]  rop;
    reg [3:0]  rsrc;
    reg [15:0] rdat, v;
    integer c, d, tbase, guard, sc_before;
    integer incr;
    reg [7:0] pre_pin_c0;

    task boot_image;
        begin
            por = 0;
            repeat (10) @(negedge clk);
            por = 1;
            repeat (5) @(negedge clk);
            saw_boot = 0; saw_epoch = 0;
            for (i = 0; i < nbytes; i = i + 1) sendbyte(imem[i]);
            @(negedge clk); s_eod = 1;
            @(negedge clk); s_eod = 0;
            waitrun;
            check(s_state === 3'd5, "boot reached RUN");
            check(saw_boot === 1'b1, "boot_ok pulse seen");
            check(saw_epoch === 1'b1, "epoch pulse seen");
            check(s_err === 8'd0, "boot no error");
        end
    endtask

    task bind_cells;
        begin
            for (c = 0; c < 3; c = c + 1) begin
                serflit(3'd0, 4'hF, c[3:0], c[15:0], 16'd0, 16'd0, 16'd0);
                recv_flit(rop, rsrc, rdat, "bind ACK arrives");
                check(rop === 3'd5, "bind answered with ACK (OP_ACK = 5)");
                check(rsrc === c[3:0], "bind ACK src is the bound cell");
            end
        end
    endtask

    task readback_dials(input [511:0] tag);
        integer cc, dd;
        reg [15:0] vv;
        begin
            for (cc = 0; cc < 3; cc = cc + 1)
                for (dd = 0; dd < 16; dd = dd + 1) begin
                    view(cc[3:0], 16'd2, dd[15:0], vv);
                    // dial 13 (FTRACE) is a live probe register, not
                    // image state: observe, never compare
                    if (dd == 13) begin
                        $display("OBSERVE %0s: cell %0d dial 13 (FTRACE probe) = %0d",
                                 tag, cc, vv);
                    end else if (vv !== img_dial(cc, dd)) begin
                        errors = errors + 1;
                        $display("FAIL %0s dial: cell %0d dial %0d = %0d, image says %0d",
                                 tag, cc, dd, vv, img_dial(cc, dd));
                    end
                end
            $display("OBSERVE %0s: 48 dial readbacks compared", tag);
        end
    endtask

    initial begin
        wait (nbytes > 0);
        repeat (2) @(negedge clk);

        // ================= P0/P1: boot + bind ==========================
        boot_image;
        bind_cells;
        check(dut.nodes[0].conn0.u_cell.u_core.cell_id === 4'd0, "P1 cell_id 0");
        check(dut.nodes[1].connc.u_cell.u_core.cell_id === 4'd1, "P1 cell_id 1");
        check(dut.nodes[2].connc.u_cell.u_core.cell_id === 4'd2, "P1 cell_id 2");
        $display("OBSERVE P1: BIND x3 ACKed; core cell_id registers = 0,1,2");

        // ================= P2: dial readback vs image =================
        readback_dials("P2 post-boot dials == image rows");

        // ================= P3: links =================================
        // workflow edge id1 -> id2 (addr 0 -> 1), base 16384: pairing at
        // the destination (cell 0 holds the synapse for peer 1 used when
        // cell 0 RECEIVES; cell 1 holds the synapse for peer 0)
        serflit(3'd1, 4'd1, 4'd0, 16'd0, 16'd16384, 16'd0, 16'd0); // dst0 src1 slot0
        serflit(3'd1, 4'd0, 4'd1, 16'd0, 16'd16384, 16'd0, 16'd0); // dst1 src0 slot0
        // workflow edge id2 -> id3 (addr 1 -> 2): cell 1's synapse for
        // peer 2 at slot 1 (its slot 0 is taken by peer 0)
        serflit(3'd1, 4'd2, 4'd1, 16'd1, 16'd16384, 16'd0, 16'd0); // dst1 src2 slot1
        repeat (200) @(negedge clk);
        view(4'd0, 16'd1, 16'd0, v);
        check(v === 16'd16384, "P3 wsum cell0 = slot0 base 16384");
        view(4'd1, 16'd1, 16'd0, v);
        check(v === 16'd32768, "P3 wsum cell1 = two bases 16384+16384");
        view(4'd2, 16'd1, 16'd0, v);
        check(v === 16'd0, "P3 wsum cell2 = 0 (no pairing yet)");

        // negative probe: EFFECT with unmatched src is silently dropped
        sc_before = sc;
        serflit(3'd2, 4'hF, 4'd2, 16'd0, 16'd0, 16'd0, 16'd99);
        repeat (300) @(negedge clk);
        check(sc === sc_before, "P3 unmatched EFFECT: no egress response");
        check(dut.nodes[2].connc.u_cell.u_core.act === 16'd0,
              "P3 unmatched EFFECT: act of cell2 unchanged");
        $display("OBSERVE P3: EFFECT src=EXTID dst=2 dat=99 silently dropped (no NAK, no act change)");

        // last link arms the 2 -> 1 fanout path (cell 2's synapse table
        // gets peer 1; cell 2's own fires now land on cell 1)
        serflit(3'd1, 4'd1, 4'd2, 16'd0, 16'd16384, 16'd0, 16'd0); // dst2 src1 slot0
        repeat (200) @(negedge clk);
        view(4'd2, 16'd1, 16'd0, v);
        check(v === 16'd16384, "P3 wsum cell2 = slot0 base 16384");
        $display("OBSERVE P3: LINK x4 installed; wsum readbacks = bases (16384 / 32768 / 16384)");

        // ================= P4: 16-tick dynamics window ===============
        tbase = tickcount;
        wait_ticks(tbase, 8);
        $display("OBSERVE P4 @+8 ticks: cell1 slot-for-2 buckets = %0d %0d %0d %0d %0d %0d %0d %0d",
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[0],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[1],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[2],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[3],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[4],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[5],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[6],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[7]);
        wait_ticks(tbase, 16);
        $display("OBSERVE P4 @+16 ticks: cell1 slot-for-2 buckets = %0d %0d %0d %0d %0d %0d %0d %0d hl_cnt=%0d",
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[0],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[1],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[2],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[3],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[4],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[5],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[6],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[7],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.hl_cnt);
        view(4'd1, 16'd1, 16'd0, v);
        $display("OBSERVE P4: wsum cell1 after 16 ticks = %0d (bases alone = 32768)", v);
        view(4'd0, 16'd1, 16'd0, v);
        $display("OBSERVE P4: wsum cell0 after 16 ticks = %0d (base alone = 16384)", v);
        $display("OBSERVE P4: act probes = %0d %0d %0d (cells 0,1,2)",
            $signed(dut.nodes[0].conn0.u_cell.u_core.act),
            $signed(dut.nodes[1].connc.u_cell.u_core.act),
            $signed(dut.nodes[2].connc.u_cell.u_core.act));

        // ================= P4b: intra-tick phase =======================
        // wait for a tick pulse, then sample the training edge's bucket
        // vector early in the window (post-shift, pre-train) and late
        // (post-train): the ladder increment is phase-dependent.
        tbase = tickcount;
        guard = 0;
        while (tickcount <= tbase && guard < 200000) begin
            @(negedge clk); guard = guard + 1;
        end
        repeat (10) @(negedge clk);
        $display("OBSERVE P4b early-window buckets cell1 slot-for-2 = %0d %0d %0d %0d %0d %0d %0d %0d",
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[0],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[1],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[2],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[3],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[4],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[5],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[6],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[7]);
        repeat (40) @(negedge clk);
        $display("OBSERVE P4b late-window buckets cell1 slot-for-2 = %0d %0d %0d %0d %0d %0d %0d %0d",
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[0],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[1],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[2],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[3],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[4],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[5],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[6],
            dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[7]);

        // ================= P5: naive inject ============================
        sc_before = sc;
        serflit(3'd2, 4'hF, 4'd0, 16'd0, 16'd0, 16'd0, 16'd42);
        repeat (300) @(negedge clk);
        check(sc === sc_before, "P5 naive inject: no egress response");
        check(dut.nodes[0].conn0.u_cell.u_core.act === 16'd0,
              "P5 naive inject: act of cell0 stays 0 (dropped)");
        $display("OBSERVE P5: sheet inject {cell 1, dat 42} as EFFECT src=EXTID: silently dropped at cell 0 (no edge-table match)");

        // ================= P6: port pairing + inject ===================
        serflit(3'd1, 4'hF, 4'd0, 16'd1, 16'h8000, 16'd0, 16'd0); // dst0 srcF slot1 base 32768
        // the port LINK's peer is EXTID, so its ACK egresses to the host:
        // pop it, or every later response lags by one
        recv_flit(rop, rsrc, rdat, "port LINK ACK arrives");
        check(rop === 3'd5, "port LINK answered with ACK (OP_ACK = 5)");
        check(rsrc === 4'd0, "port LINK ACK src is the linked cell");
        repeat (200) @(negedge clk);
        view(4'd0, 16'd1, 16'd0, v);
        check(v === 16'd49152, "P6 wsum cell0 = 16384 + port base 32768");
        serflit(3'd2, 4'hF, 4'd0, 16'd0, 16'd0, 16'd0, 16'd42);
        guard = 0;
        while (dut.nodes[0].conn0.u_cell.u_core.act !== 16'd42 && guard < 3000) begin
            @(negedge clk); guard = guard + 1;
        end
        check(dut.nodes[0].conn0.u_cell.u_core.act === 16'd42,
              "P6 inject lands: act cell0 = 42 (post-train w 33024, (33024*42)>>>15 = 42)");
        $display("OBSERVE P6: inject with port pairing landed after %0d cycles; act cell0 = 42; tickcount = %0d",
                 guard, tickcount);
        // ride out the next tick boundary: the step's own tick window
        tbase = tickcount;
        wait_ticks(tbase, 1);
        $display("OBSERVE P6 after 1 tick: act cell0 = %0d, act cell1 = %0d (fire threshold cell0 = 12000)",
            $signed(dut.nodes[0].conn0.u_cell.u_core.act),
            $signed(dut.nodes[1].connc.u_cell.u_core.act));
        check(dut.nodes[0].conn0.u_cell.u_core.act === 16'd0,
              "P6 act cell0 erased at first tick (KA=0: leak = act - (act>>>0) = 0)");
        check(dut.nodes[1].connc.u_cell.u_core.act === 16'd0,
              "P6 no propagation: act cell1 stays 0 (42 < THRESH 12000, cell0 never fired)");

        // ================= P7: decay series ============================
        // the port edge was trained exactly once (P6); its ladder
        // increment after s shifts is 256 >> s (HL = 0: shift every tick)
        for (d = 1; d <= 8; d = d + 1) begin
            tbase = tickcount;
            wait_ticks(tbase, 1);
            incr = dut.nodes[0].conn0.u_cell.edges[1].u_hebb.c[0] * 256
                 + dut.nodes[0].conn0.u_cell.edges[1].u_hebb.c[1] * 128
                 + dut.nodes[0].conn0.u_cell.edges[1].u_hebb.c[2] * 64
                 + dut.nodes[0].conn0.u_cell.edges[1].u_hebb.c[3] * 32
                 + dut.nodes[0].conn0.u_cell.edges[1].u_hebb.c[4] * 16
                 + dut.nodes[0].conn0.u_cell.edges[1].u_hebb.c[5] * 8
                 + dut.nodes[0].conn0.u_cell.edges[1].u_hebb.c[6] * 4
                 + dut.nodes[0].conn0.u_cell.edges[1].u_hebb.c[7] * 2;
            $display("OBSERVE P7: port-edge ladder increment after decay tick %0d = %0d", d, incr);
        end
        view(4'd0, 16'd1, 16'd0, v);
        $display("OBSERVE P7: wsum cell0 at end of decay series = %0d (49152 at P6)", v);
        view(4'd1, 16'd1, 16'd0, v);
        $display("OBSERVE P7: wsum cell1 still training-fed = %0d (32768 = bases alone)", v);

        // ================= P8: final dials =============================
        readback_dials("P8 post-run dials == image rows");

        // ================= P9: compensation run ========================
        boot_image;
        bind_cells;
        // links, same order as P3 + port pairing
        serflit(3'd1, 4'd1, 4'd0, 16'd0, 16'd16384, 16'd0, 16'd0);
        serflit(3'd1, 4'd0, 4'd1, 16'd0, 16'd16384, 16'd0, 16'd0);
        serflit(3'd1, 4'd2, 4'd1, 16'd1, 16'd16384, 16'd0, 16'd0);
        serflit(3'd1, 4'd1, 4'd2, 16'd0, 16'd16384, 16'd0, 16'd0);
        serflit(3'd1, 4'hF, 4'd0, 16'd1, 16'h8000, 16'd0, 16'd0);
        recv_flit(rop, rsrc, rdat, "P9 port LINK ACK arrives");
        check(rop === 3'd5, "P9 port LINK answered with ACK");
        check(rsrc === 4'd0, "P9 port LINK ACK src is cell 0");
        repeat (200) @(negedge clk);
        // pins via BIND dial writes (a0 = dial index, a1 = value)
        for (c = 0; c < 3; c = c + 1) begin
            serflit(3'd0, 4'hF, c[3:0], 16'd4,  16'd15,    16'd0, 16'd0); // KA := 15
            recv_flit(rop, rsrc, rdat, "pin KA ACK");
            serflit(3'd0, 4'hF, c[3:0], 16'd10, 16'hFFFF, 16'd0, 16'd0); // HL := 65535
            recv_flit(rop, rsrc, rdat, "pin HL ACK");
        end
        serflit(3'd0, 4'hF, 4'd2, 16'd5, 16'h7FFF, 16'd0, 16'd0); // sink THRESH := 32767
        recv_flit(rop, rsrc, rdat, "pin THRESH ACK");
        view(4'd2, 16'd2, 16'd5, v);
        check(v === 16'h7FFF, "P9 sink THRESH pinned to 32767");
        view(4'd0, 16'd2, 16'd4, v);
        check(v === 16'd15, "P9 KA pinned to 15");
        view(4'd0, 16'd2, 16'd10, v);
        check(v === 16'hFFFF, "P9 HL pinned to 65535");
        // trains landed before the THRESH pin are already in bucket0;
        // the frozen claim is that the window adds NOTHING
        view(4'd1, 16'd1, 16'd0, v);
        pre_pin_c0 = dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[0];
        $display("OBSERVE P9: wsum cell1 at pin time = %0d; slot-for-2 bucket0 = %0d",
                 v, pre_pin_c0);
        tbase = tickcount;
        wait_ticks(tbase, 16);
        view(4'd1, 16'd1, 16'd0, v);
        $display("OBSERVE P9: wsum cell1 after 16 pinned ticks = %0d; slot-for-2 bucket0 = %0d",
                 v, dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[0]);
        check(dut.nodes[1].connc.u_cell.edges[1].u_hebb.c[0] === pre_pin_c0,
              "P9 no new trains in 16 pinned ticks (bucket0 unchanged)");
        // inject again under the pins
        serflit(3'd2, 4'hF, 4'd0, 16'd0, 16'd0, 16'd0, 16'd42);
        guard = 0;
        while (dut.nodes[0].conn0.u_cell.u_core.act !== 16'd42 && guard < 3000) begin
            @(negedge clk); guard = guard + 1;
        end
        check(dut.nodes[0].conn0.u_cell.u_core.act === 16'd42,
              "P9 inject lands: act cell0 = 42");
        tbase = tickcount;
        wait_ticks(tbase, 8);
        $display("OBSERVE P9: act cell0 after 8 pinned ticks = %0d; act cell1 = %0d",
            $signed(dut.nodes[0].conn0.u_cell.u_core.act),
            $signed(dut.nodes[1].connc.u_cell.u_core.act));
        check(dut.nodes[0].conn0.u_cell.u_core.act === 16'd42,
              "P9 act survives 8 ticks under KA=15 (leak 42>>>15 = 0)");
        view(4'd0, 16'd1, 16'd0, v);
        $display("OBSERVE P9: wsum cell0 after 8 pinned ticks = %0d (expect 49408 = 16384 + 32768 + 256 unshifted train)", v);
        check(v === 16'd49408, "P9 trained increment persists unshifted under HL pin");
        check(dut.nodes[1].connc.u_cell.u_core.act === 16'd0,
              "P9 still no propagation (42 < THRESH 12000 under any decay pins)");

        if (errors == 0)
            $display("LANE_BEHAVIOUR PASS: booted fabric driven through the lowered op sequence; all fabric-side predictions held (see OBSERVE lines)");
        else
            $display("LANE_BEHAVIOUR FAIL: %0d error(s)", errors);
        $finish;
    end

    // global watchdog
    initial begin
        #200_000_000;
        $display("LANE_BEHAVIOUR FAIL: global timeout (state=%0d err=%0d sc=%0d consumed=%0d)",
                 s_state, s_err, sc, consumed);
        $finish;
    end
endmodule
