// tb_quf_boot.v -- boot harness tests (quilt-verilog v2.1, FPGA round 3).
//
// Four acceptance cases over rtl/quf_boot.v + rtl/q_uf_loader.v on the
// golden container built by tools/quf.py from tb/quf_tb.json (byte image
// tb/run/lane_boot.hex; regenerate with tools/run_quf_tb.sh or
// `python3 tools/quf.py create tb/quf_tb.json tb/run/quf_tb_input.quf`):
//
//   1. WARM   : a valid QUF byte stream boots the fabric: dials row for
//               cell 0 lands byte-exact (dial5=0x5000, hl=0x30), loader
//               tpw=6 is LATCHED as the epoch, o_rst_n releases exactly
//               in RUN, and the runtime qm_bind dial port goes live
//               (write+readback) -- the mutual-exclusion mux flips.
//               During LOAD a qm write is refused (exclusion by
//               construction, verified, not assumed).
//   2. CORRUPT: bad magic -> loader err 1 -> sticky HOLD_ERR, fabric held
//               in reset forever, dials at POR defaults (fail-static to
//               the bit-exact v1 configuration), no boot_ok, no epoch.
//   3. TRUNC  : stream cut mid-file + i_eod -> E_TRUNC(10) -> HOLD_ERR,
//               fabric never released, qm writes dead (the half-image
//               never runs; recovery is POR).
//   4. EPOCH  : after a clean boot, transport noise (bytes + eod) changes
//               nothing: state stays RUN, tpw stays latched, dials only
//               move via qm_bind. Latch-once-at-release, refused by
//               construction.
//
// Run: iverilog -g2005 -o tb/run/tb_quf_boot.vvp \
//        rtl/q_uf_loader.v rtl/quf_boot.v rtl/q_dialfile.v \
//        tb/tb_quf_boot.v && vvp tb/run/tb_quf_boot.vvp
`timescale 1ns/1ps
module tb_lane_boot;
    reg clk = 0, rst_n = 0;
    always #5 clk = ~clk;

    integer errors = 0;

    // transport
    reg         i_bval = 0, i_eod = 0;
    reg  [7:0]  i_byte = 0;
    wire        o_brdy;

    // runtime qm_bind port
    reg         i_qm_wr = 0;
    reg  [3:0]  i_qm_addr = 0;
    reg  [15:0] i_qm_wdata = 0;

    // boot outputs
    wire        df_wr;
    wire [3:0]  df_addr;
    wire [15:0] df_wdata;
    wire        edge_wr;
    wire [3:0]  edge_addr;
    wire [31:0] edge_data;
    wire        route_wr;
    wire [3:0]  route_dst, route_via;
    wire [4:0]  tpw;
    wire        epoch, rst_out, boot_ok;
    wire [2:0]  state;
    wire [7:0]  err;

    // dialfile: POR-reset ONLY (not rst_out) -- boot writes must stick
    // while the fabric is frozen (docs/FPGA-BOOT.md §2 reset topology)
    reg         df_rd = 0;
    wire [15:0] df_rdata;
    wire        df_rstb;
    wire [15:0] d_eta_f, d_eta_s, d_refr, d_cosmin, d_floor, d_hl;
    wire [3:0]  d_kf, d_ks, d_ka, d_kle, d_qdw, d_qleak;
    wire signed [15:0] d_thresh;
    wire [4:0]  d_p0e;
    wire        d_mode, d_rqen;

    quf_boot #(.AIDW(4)) u_boot (
        .clk(clk), .rst_n(rst_n),
        .i_bval(i_bval), .o_brdy(o_brdy), .i_byte(i_byte), .i_eod(i_eod),
        .i_mycell(4'd0),
        .i_qm_wr(i_qm_wr), .i_qm_addr(i_qm_addr), .i_qm_wdata(i_qm_wdata),
        .o_df_wr(df_wr), .o_df_addr(df_addr), .o_df_wdata(df_wdata),
        .o_edge_wr(edge_wr), .o_edge_addr(edge_addr),
        .o_edge_data(edge_data),
        .o_route_wr(route_wr), .o_route_dst(route_dst),
        .o_route_via(route_via),
        .o_tpw(tpw), .o_epoch(epoch),
        .o_rst_n(rst_out), .o_boot_ok(boot_ok),
        .o_state(state), .o_err(err)
    );


    q_dialfile #(.DW(16), .ND(16), .AW(4)) u_df (
        .clk(clk), .rst_n(rst_n),
        .i_wr(df_wr), .i_addr(df_addr), .i_wdata(df_wdata),
        .i_rd(df_rd), .o_rdata(df_rdata), .o_rstb(df_rstb),
        .o_eta_f(d_eta_f), .o_eta_s(d_eta_s),
        .o_kf(d_kf), .o_ks(d_ks), .o_ka(d_ka),
        .o_thresh(d_thresh), .o_refr(d_refr), .o_cosmin(d_cosmin),
        .o_p0e(d_p0e), .o_mode(d_mode), .o_hl(d_hl),
        .i_probe(16'd0),
        .o_kle(d_kle), .o_floor(d_floor),
        .o_qdw(d_qdw), .o_qleak(d_qleak), .o_rqen(d_rqen)
    );

    // edge / route RAM shadows
    reg [31:0] eram [0:3];
    reg [3:0]  rram [0:15];
    integer i;
    initial begin
        // INCIDENTS x1000 rule: probe prints carry explicit units
        // (%t otherwise formats in the finest declared precision, ps here)
        $timeformat(-9, 0, " ns", 10);
        for (i = 0; i < 4; i = i + 1)  eram[i] = 32'h0;
        for (i = 0; i < 16; i = i + 1) rram[i] = 4'h0;
    end
    always @(posedge clk) begin
        if (rst_n) begin
            if (edge_wr)  eram[edge_addr]  <= edge_data;
            if (route_wr) rram[route_dst]  <= route_via;
        end
    end

    // boot_ok / epoch pulse catchers
    reg saw_boot_ok = 0, saw_epoch = 0;
    // pulse catching on the WIRE EDGE itself (no clocked region, no NBA
    // commit window): simulator-scheduling-proof by construction
    always @(boot_ok) if (boot_ok === 1'b1) saw_boot_ok = 1;
    always @(epoch)   if (epoch   === 1'b1) saw_epoch   = 1;

    // ---------------------------------------------------------- helpers
    task check(input cond, input [255:0] name);
        begin
            if (cond !== 1'b1) begin
                errors = errors + 1;
                $display("FAIL %0s (t=%0t state=%0d err=%0d)",
                         name, $time, state, err);
            end
        end
    endtask

    task sendbyte(input [7:0] b);
        begin
            @(negedge clk);
            i_bval = 1; i_byte = b;
            while (o_brdy !== 1'b1) @(negedge clk);
            @(negedge clk);
            i_bval = 0;
        end
    endtask

    // dial read through the RUN-path address mux (i_qm_addr drives
    // o_df_addr in RUN; dialfile reads on i_rd)
    task rddial(input [3:0] a, output [15:0] d);
        begin
            @(negedge clk);
            i_qm_addr = a; df_rd = 1;
            @(negedge clk);
            df_rd = 0; d = df_rdata;
        end
    endtask

    task qmwrite(input [3:0] a, input [15:0] v);
        begin
            @(negedge clk);
            i_qm_wr = 1; i_qm_addr = a; i_qm_wdata = v;
            @(negedge clk);
            i_qm_wr = 0;
        end
    endtask

    task full_por;
        begin
            @(negedge clk); rst_n = 0;
            repeat (3) @(negedge clk);
            saw_boot_ok = 0; saw_epoch = 0;
            @(negedge clk); rst_n = 1;
            repeat (3) @(negedge clk);
        end
    endtask

    // wait for a state with timeout
    task waitstate(input [2:0] s, input integer limit, output ok);
        integer n;
        begin
            ok = 0;
            for (n = 0; n < limit; n = n + 1) begin
                @(posedge clk);
                if (state === s) begin ok = 1; n = limit; end
            end
            repeat (2) @(negedge clk);   // let pulse-catcher NBAs commit
                                            // (verilator samples posedge
                                            // state a cycle earlier)
        end
    endtask

    // ---------------------------------------------------------- image --
    integer fd, r, nbytes, tmpi;
    reg [7:0] imem [0:65535];
    reg [15:0] rd;
    integer okw;
    reg ok;
    integer ncbytes;
    reg [7:0] cmem [0:65535];

    initial begin
        fd = $fopen("tb/run/lane_boot.hex", "r");
        if (fd == 0) begin
            $display("FAIL: cannot open tb/run/lane_boot.hex (run tools/run_quf_tb.sh or quf.py create first)");
            $finish;
        end
        r = $fscanf(fd, "%h", nbytes);
        if (r != 1 || nbytes <= 0 || nbytes > 65536 || (nbytes % 2) != 0) begin
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
        $display("LANE_BOOT: %0d-byte lane-sheets image", nbytes);
    end

    initial begin
        // wait for image load
        wait (nbytes > 0);
        repeat (2) @(negedge clk);

        // ================= CASE 1: valid QUF warm-start ================
        full_por;
        check(state === 3'd1, "c1 POR->HOLD");
        // poison: a qm write during the boot window must be refused
        i_qm_wr = 0;
        i_qm_addr = 4'd3; i_qm_wdata = 16'hBEEF;
        @(negedge clk); i_qm_wr = 1;
        // stream the whole container bytewise
        for (i = 0; i < nbytes; i = i + 1) begin
            sendbyte(imem[i]);
            // hold the attempted qm write through the boot window proper
            // (LOAD and earlier; drop before done can release the fabric)
            i_qm_wr = (i < nbytes / 2);
        end
        @(negedge clk); i_qm_wr = 0;
        waitstate(3'd5, 20000, ok);
        check(ok === 1'b1, "c1 reached RUN");
        check(saw_boot_ok === 1'b1, "c1 boot_ok pulse");
        check(saw_epoch === 1'b1, "c1 epoch pulse");
        check(rst_out === 1'b1, "c1 fabric released");
        check(err === 8'd0, "c1 no error");
        check(tpw === 5'd6, "c1 tpw latched = 6");
        rddial(4'd5, rd);  check(rd === 16'h2EE0, "c1 dial5 warm value (12000)");
        rddial(4'd10, rd); check(rd === 16'h0000, "c1 dial10 hl (0)");
        rddial(4'd3, rd);  check(rd !== 16'hBEEF, "c1 qm write refused during LOAD");
        check(eram[0] === 32'h4000_0100, "c1 edge0 landed");
        check(eram[1] === 32'h0, "c1 no second src0 edge");
        check(eram[2] === 32'h0, "c1 src1 edge filtered");
        // qm port live now: write + readback through the mux
        qmwrite(4'd5, 16'h1234);
        rddial(4'd5, rd);  check(rd === 16'h1234, "c1 qm write live in RUN");

        if (errors == 0)
            $display("LANE_BOOT PASS: lane-sheets QUF warm-start boots the fabric -- RUN reached, epoch latched, dial + edge readback byte-exact");
        else
            $display("LANE_BOOT FAIL: %0d error(s)", errors);
        $finish;
    end

    // global watchdog
    initial begin
        #50_000_000;
        $display("LANE_BOOT FAIL: global timeout (state=%0d err=%0d)",
                 state, err);
        $finish;
    end
endmodule
