<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('raw_payloads', function (Blueprint $table) {
            $table->id();
            $table->foreignId('supplier_id')->constrained()->cascadeOnDelete();
            $table->string('service', 40);
            $table->string('method', 80);
            $table->char('request_hash', 64);
            $table->char('response_hash', 64);
            // File on the raw disk (gzip). The database only keeps the pointer, never the XML.
            $table->string('storage_path', 500);
            $table->unsignedBigInteger('bytes');
            $table->unsignedSmallInteger('http_status')->nullable();
            $table->timestamp('fetched_at');
            $table->timestamps();

            // Lets the normalizer skip responses identical to the last one stored.
            $table->index(['supplier_id', 'service', 'method', 'response_hash'], 'raw_payloads_lookup');
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('raw_payloads');
    }
};
