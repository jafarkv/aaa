<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('sync_runs', function (Blueprint $table) {
            $table->id();
            $table->foreignId('supplier_id')->constrained()->cascadeOnDelete();
            $table->string('service', 40);
            $table->string('tier', 40);              // full | delta | pricing | inventory | test ...
            $table->string('status', 20)->default('running'); // running | success | partial | failed
            $table->timestamp('started_at');
            $table->timestamp('finished_at')->nullable();
            $table->unsignedInteger('items_seen')->default(0);
            $table->unsignedInteger('items_changed')->default(0);
            $table->unsignedInteger('error_count')->default(0);
            $table->timestamps();

            $table->index(['supplier_id', 'service', 'started_at']);
        });

        Schema::create('sync_errors', function (Blueprint $table) {
            $table->id();
            $table->foreignId('sync_run_id')->nullable()->constrained()->nullOnDelete();
            $table->foreignId('supplier_id')->constrained()->cascadeOnDelete();
            $table->string('service', 40);
            $table->string('method', 80)->nullable();
            $table->text('message');
            $table->json('context')->nullable();    // never put credentials in here
            $table->timestamps();

            $table->index(['supplier_id', 'created_at']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('sync_errors');
        Schema::dropIfExists('sync_runs');
    }
};
