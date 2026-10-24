// tb_quf_loader.v -- end-to-end QUF load test (quilt-verilog v1).
// Flow: tools/quf.py builds a golden QUF from tb/quf_tb.json and emits a
// byte-per-line .hex; this TB streams those bytes (16-bit LE words) into
// q_uf_loader and asserts, byte-exact, that:
//   - the mycell dial row landed in q_dialfile (port read-back + fan-outs)
//   - edge RAM words {base,dst,mode} match the golden edges for src==mycell
//     (and the src!=mycell edge did NOT land)
//   - route RAM nibbles and the tick exponent match
// Run: tools/run_quf_tb.sh (python create -> iverilog -> vvp).
`timescale 1ns/1ps
module tb_lane_load;
    reg clk = 0, rst_n = 0;
    always #5 clk = ~clk;

    // stream source
    reg         i_val = 0;
    reg  [15:0] i_dat = 0;
    wire        o_rdy;

    // loader <-> state targets
    wire        dial_wr;
    wire [3:0]  dial_addr;
    wire [15:0] dial_wdata;
    wire        edge_wr;
    wire [3:0]  edge_addr;
    wire [31:0] edge_data;
    wire        route_wr;
    wire [3:0]  route_dst, route_via;
    wire [4:0]  tick_tpw;
    wire        done;
    wire [7:0]  err;

    // q_dialfile has one shared address port (as in q_cell: the core muxes);
    // TB muxes: loader writes while loading, read probes otherwise
    reg         df_rd = 0;
    reg  [3:0]  df_addr = 0;
    wire [3:0]  df_addr_mux = df_rd ? df_addr : dial_addr;
    wire [15:0] df_rdata;
    wire        df_rstb;
    wire [15:0] d_eta_f, d_eta_s, d_refr, d_cosmin, d_hl;
    wire [3:0]  d_kf, d_ks, d_ka;
    wire signed [15:0] d_thresh;
    wire [4:0]  d_p0e;
    wire        d_mode;

    integer errors = 0;

    q_uf_loader #(.AIDW(4)) u_ld (
        .clk(clk), .rst_n(rst_n),
        .i_val(i_val), .o_rdy(o_rdy), .i_dat(i_dat),
        .i_mycell(4'd0),
        .o_dial_wr(dial_wr), .o_dial_addr(dial_addr),
        .o_dial_wdata(dial_wdata),
        .o_edge_wr(edge_wr), .o_edge_addr(edge_addr),
        .o_edge_data(edge_data),
        .o_route_wr(route_wr), .o_route_dst(route_dst),
        .o_route_via(route_via),
        .o_tick_tpw(tick_tpw),
        .o_done(done), .o_err(err)
    );

    q_dialfile #(.DW(16), .ND(16), .AW(4)) u_df (
        .clk(clk), .rst_n(rst_n),
        .i_wr(dial_wr), .i_addr(df_addr_mux), .i_wdata(dial_wdata),
        .i_rd(df_rd), .o_rdata(df_rdata), .o_rstb(df_rstb),
        .o_eta_f(d_eta_f), .o_eta_s(d_eta_s),
        .o_kf(d_kf), .o_ks(d_ks), .o_ka(d_ka),
        .o_thresh(d_thresh), .o_refr(d_refr), .o_cosmin(d_cosmin),
        .o_p0e(d_p0e), .o_mode(d_mode), .o_hl(d_hl)
    );

    // edge RAM: the loader's target (as in a cell's edge table)
    reg [31:0] eram [0:3];
    // route RAM indexed by dst nibble
    reg [3:0]  rram [0:15];

    integer i;
    initial begin
        for (i = 0; i < 4; i = i + 1)  eram[i] = 32'h0;
        for (i = 0; i < 16; i = i + 1) rram[i] = 4'h0;
    end

    always @(posedge clk) begin
        if (edge_wr) eram[edge_addr] <= edge_data;
        if (route_wr) rram[route_dst] <= route_via;
    end

    // ------------------------------------------------------------ helpers
    task check16(input [15:0] got, input [15:0] exp, input [127:0] name);
        begin
            if (got !== exp) begin
                errors = errors + 1;
                $display("FAIL %0s: got %h exp %h", name, got, exp);
            end
        end
    endtask

    task check32(input [31:0] got, input [31:0] exp, input [127:0] name);
        begin
            if (got !== exp) begin
                errors = errors + 1;
                $display("FAIL %0s: got %h exp %h", name, got, exp);
            end
        end
    endtask

    task sendw(input [15:0] w);
        integer ok;
        begin
            ok = 0;
            @(negedge clk);
            i_val = 1;
            i_dat = w;
            while (!ok) begin
                @(posedge clk);
                if (o_rdy === 1'b1)
                    ok = 1;            // handshake completed at this edge
                else if (done === 1'b1)
                    ok = 2;            // loader finished: padding, abandon
            end
            @(negedge clk);
            i_val = 0;
        end
    endtask

    // q_dialfile read: drive i_rd for one cycle, sample registered output
    task rddial(input [3:0] a, output [15:0] d);
        begin
            @(negedge clk);
            df_rd   = 1;
            df_addr = a;
            @(negedge clk);
            df_rd   = 0;
            d       = df_rdata;
        end
    endtask

    // -------------------------------------------------------------- file
    integer fd, r, nbytes, tmpi;
    reg [7:0] imem [0:65535];
    reg [15:0] rd;

    initial begin
        fd = $fopen("tb/run/lane_input.hex", "r");
        if (fd == 0) begin
            $display("FAIL: cannot open tb/run/lane_input.hex (run tools/quf.py create first)");
            $finish;
        end
        r = $fscanf(fd, "%h", nbytes);
        if (r != 1 || nbytes <= 0 || nbytes > 65536 || (nbytes % 2) != 0) begin
            $display("FAIL: bad hex file header (r=%0d n=%0d)", r, nbytes);
            $finish;
        end
        for (i = 0; i < nbytes; i = i + 1) begin
            r = $fscanf(fd, "%h", tmpi);
            if (r != 1) begin
                $display("FAIL: hex file truncated at byte %0d", i);
                $finish;
            end
            imem[i] = tmpi[7:0];
        end
        $fclose(fd);
        $display("LANE_TB: read %0d bytes from hex image", nbytes);
    end

    // ------------------------------------------------------------ main --
    integer tmo;
    initial begin
        repeat (4) @(negedge clk);
        rst_n = 1;
        repeat (2) @(negedge clk);

        // stream the whole container, 16-bit little-endian words
        for (i = 0; i < nbytes; i = i + 2)
            sendw({imem[i+1], imem[i]});

        // wait for load completion
        tmo = 0;
        while (done !== 1'b1 && tmo < 20000) begin
            @(posedge clk);
            tmo = tmo + 1;
        end
        if (done !== 1'b1) begin
            errors = errors + 1;
            $display("FAIL: loader never asserted done (timeout)");
        end
        if (err !== 8'd0) begin
            errors = errors + 1;
            $display("FAIL: loader error code %0d", err);
        end
        @(negedge clk);

        // ---- dials: byte-exact row image for cell 0 (lane-sheets
        // triage-clean; fabric address 0 = workflow cell id 1 "inbox",
        // dials [0,0,0,0,0,12000,0,0,0,0,0,0,0,0,0,0])
        rddial(4'd0,  rd);  check16(rd, 16'h0000, "dial0");
        rddial(4'd5,  rd);  check16(rd, 16'h2EE0, "dial5_thresh_12000");
        rddial(4'd15, rd);  check16(rd, 16'h0000, "dial15_rsv");
        // combinational fan-out proves the image is live fabric state
        check16(d_thresh, 16'h2EE0, "fanout_thresh");
        // address-1 row (thresh 8000 = 0x1F40) must NOT have leaked
        if (d_thresh === 16'h1F40) begin
            errors = errors + 1;
            $display("FAIL: wrong-cell dial row leaked");
        end

        // ---- edges: src==0 record lands byte-exact; src==1 does not
        check32(eram[0], 32'h4000_0100, "edge0_{base=0x4000,dst=1,mode=0}");
        check32(eram[1], 32'h0000_0000, "edge1_untouched_by_src1");

        // ---- routing (identity per QUF-NOTES D2) + tick exponent
        if (rram[1] !== 4'd1 || rram[2] !== 4'd2
            || rram[0] !== 4'd0 || rram[15] !== 4'd0) begin
            errors = errors + 1;
            $display("FAIL: route RAM got %0d %0d %0d %0d",
                     rram[0], rram[1], rram[2], rram[15]);
        end
        if (tick_tpw !== 5'd6) begin
            errors = errors + 1;
            $display("FAIL: tick_tpw got %0d exp 6", tick_tpw);
        end

        if (errors == 0)
            $display("LANE_TB PASS: %0d-byte QUF loaded, dial + edge readback byte-exact", nbytes);
        else
            $display("LANE_TB FAIL: %0d error(s)", errors);
        $finish;
    end

    // global watchdog
    initial begin
        #10_000_000;
        $display("LANE_TB FAIL: global timeout");
        $finish;
    end

endmodule
